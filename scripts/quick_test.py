#!/usr/bin/env python3
from __future__ import annotations
import os

from mtc_processor.config import AppConfig
from mtc_processor.ingest import IngestClient
from mtc_processor.transform import parse_mtconnect
from mtc_processor.runner import build_processors
from mtc_processor.storage.dryrun import DryRunStore


def main():
    # Force dry-run and sample-file read regardless of YAML
    cfg = AppConfig.from_env()
    cfg.influx.enabled = False
    cfg.ingest.url = None
    if not cfg.ingest.sample_file:
        cfg.ingest.sample_file = os.getenv("MTC_SAMPLE_PATH", "/app/MTConnect-sample/Haas-current.xml")

    xml_text = IngestClient(None, sample_file=cfg.ingest.sample_file).get_current_xml()
    points = parse_mtconnect(xml_text)

    store = DryRunStore(limit=10)
    # Same processors as the real runner, so this check cannot drift from it
    for p in build_processors(cfg):
        p.process(points, store)


if __name__ == "__main__":
    main()
