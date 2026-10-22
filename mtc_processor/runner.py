from __future__ import annotations
import os
import time
import warnings
from datetime import datetime, timezone
from typing import List

import urllib3
warnings.filterwarnings("ignore", category=urllib3.exceptions.InsecureRequestWarning)

from .config import AppConfig
from .ingest import IngestClient
from .transform import parse_mtconnect
from .logutil import get_processor_logger
from .dedupe import ItemSequenceDeduper
from .processors.base import BaseStore
from .processors.metrics import MetricsProcessor
from .storage.buffered import BufferedStore
from .storage.influx import InfluxStore
from .storage.dryrun import DryRunStore


_LAST_MACHINE_STATUS: dict[str, str] = {}


def build_store(cfg: AppConfig) -> BufferedStore:
    if cfg.influx.enabled and cfg.influx.token:
        target = InfluxStore(url=cfg.influx.url, token=cfg.influx.token, org=cfg.influx.org, bucket=cfg.influx.bucket)
    else:
        # Fallback to dry-run store (stdout)
        target = DryRunStore()
    # Rows wait here while the database cannot be reached
    return BufferedStore(target, cfg.influx.buffer_max_rows)


def build_processors(cfg: AppConfig):
    return [
        MetricsProcessor(cfg.mapping.numeric_elements, cfg.mapping.status_elements),
    ]


def run_once(
    cfg: AppConfig,
    store: BaseStore,
    deduper: ItemSequenceDeduper | None = None,
    log_raw_points: bool = False,
    skip_dedupe: bool = False,
):
    logger = get_processor_logger("runner")
    ingest = IngestClient(
        base_url=cfg.ingest.url,
        timeout_seconds=cfg.ingest.timeout_seconds,
        sample_file=cfg.ingest.sample_file,
    )
    try:
        xml_text = ingest.get_current_xml()
    except Exception as e:
        logger.error("Ingest failed: %s", e)
        _write_machine_status(store, cfg, online=False)
        store.flush()
        return
    points = parse_mtconnect(xml_text)
    if log_raw_points:
        for p in points:
            logger.info(
                "Raw point -> section=%s name=%s element=%s component=%s value=%s timestamp=%s sequence=%s",
                (p.get("section") or ""),
                (p.get("name") or ""),
                (p.get("element") or ""),
                (p.get("component_name") or p.get("component") or ""),
                (p.get("value") or ""),
                (p.get("timestamp") or ""),
                (p.get("sequence") or ""),
            )
    _write_machine_status(store, cfg, online=bool(points))
    logger.info("Points before dedupe: %d", len(points))
    if skip_dedupe:
        logger.info("Skipping dedupe for startup poll")
    if not skip_dedupe and cfg.dedupe.enabled:
        if deduper is None:
            deduper = ItemSequenceDeduper()
        before2 = len(points)
        points = deduper.filter(points)
        after2 = len(points)
        if before2 != after2:
            print(f"Deduped by sequence: {before2} -> {after2}")
    logger.info("Points after dedupe: %d", len(points))
    processors = build_processors(cfg)
    for proc in processors:
        proc.process(points, store)


def _write_machine_status(store: BaseStore, cfg: AppConfig, online: bool) -> None:
    state = 1 if online else 0
    device = cfg.device_uuid or cfg.device_name or "unknown"
    last_state = _LAST_MACHINE_STATUS.get(device)
    if last_state == state:
        return
    _LAST_MACHINE_STATUS[device] = state
    tags = {
        "device": device,
        "component": "machine",
        "name": "machine_status",
    }
    fields = {"online": state}
    timestamp = datetime.now(timezone.utc).isoformat()
    store.write_point("mtc_status", tags, fields, timestamp)


def main():
    cfg = AppConfig.from_env()
    interval = float(os.getenv("POLL_INTERVAL", "10"))
    print("Starting MTConnect processor")
    # Avoid printing sensitive token
    print(
        "Config: "
        f"device={cfg.device_name or cfg.device_uuid}, "
        f"ingest_url={cfg.ingest.url}, "
        f"influx_enabled={cfg.influx.enabled}, "
        f"influx_url={cfg.influx.url}, org={cfg.influx.org}, bucket={cfg.influx.bucket}, "
        f"token_set={'yes' if bool(cfg.influx.token) else 'no'}"
    )
    run_once_flag = os.getenv("RUN_ONCE", "0") in ("1", "true", "True")
    deduper = ItemSequenceDeduper() if cfg.dedupe.enabled else None
    store = build_store(cfg)
    if run_once_flag:
        run_once(cfg, store, deduper, log_raw_points=True, skip_dedupe=True)
        store.close()
        return
    first_run = True
    while True:
        try:
            run_once(cfg, store, deduper, log_raw_points=first_run, skip_dedupe=first_run)
        except Exception as e:
            print(f"Error in processing loop: {e}")
        first_run = False
        time.sleep(interval)


if __name__ == "__main__":
    main()
