"""Focused tests: parsing, processing, de-duplication and buffering of MTConnect data.

No network and no InfluxDB: points are written to an in-memory store. Run in the
test container:

    dev/test.sh unit
"""
import os
import unittest
from pathlib import Path
from unittest import mock

from mtc_processor.config import AppConfig
from mtc_processor.dedupe import ItemSequenceDeduper
from mtc_processor.processors.base import BaseStore, RejectedError
from mtc_processor.runner import build_processors, run_once
from mtc_processor.storage.buffered import BufferedStore
from mtc_processor.transform import parse_mtconnect

REPO_DIR = Path(__file__).resolve().parents[1]
SAMPLE_XML = REPO_DIR / "MTConnect-sample" / "Haas-current.xml"
EXAMPLE_CONFIG = REPO_DIR / "config" / "mtc_config.example.yaml"

SAMPLE_DEVICE_UUID = "MAZAK-SAMPLE-0001"
SECTIONS = {"Samples", "Events", "Condition"}

# The shape downstream consumers rely on: measurement, tag set and field per measurement.
METRICS = "mtc_metrics"
STATUS = "mtc_status"
EXPECTED_TAGS = {"device", "component", "element", "name"}
EXPECTED_FIELD = {METRICS: "value", STATUS: "state"}
# Listed in the example config's numeric_elements and numeric in the sample
KNOWN_METRIC_NAME = "cload"
# Agent online/offline row written by the runner itself, not from the XML
MACHINE_STATUS_NAME = "machine_status"


class RecordingStore(BaseStore):
    """Test double: keeps written points in memory."""

    def __init__(self):
        self.points = []

    def write_point(self, measurement, tags, fields, timestamp):
        self.points.append((measurement, tags, fields, timestamp))


class FlakyStore(RecordingStore):
    """Test double: raises `error` instead of storing while it is set."""

    def __init__(self):
        super().__init__()
        self.error = None

    def write_points(self, rows):
        if self.error:
            raise self.error
        super().write_points(rows)


def _status_row(name, second):
    """One mtc_status row of the data item `name`, written at the given second."""
    timestamp = f"2025-10-29T12:00:{second:02d}Z"
    return STATUS, {"name": name}, {"state": timestamp}, timestamp


def _sample_points():
    return parse_mtconnect(SAMPLE_XML.read_text(encoding="utf-8"))


def _load_config(**env):
    """Loads the example config with exactly the given environment."""
    with mock.patch.dict(os.environ, env, clear=True):
        return AppConfig.load(str(EXAMPLE_CONFIG))


def _process_sample():
    store = RecordingStore()
    points = _sample_points()
    for processor in build_processors(_load_config()):
        processor.process(points, store)
    return store.points


def _poll_sample_twice(dedupe_enabled):
    """Two polls of the sample through runner.run_once; returns the data rows of each."""
    cfg = _load_config()
    cfg.ingest.sample_file = str(SAMPLE_XML)
    cfg.dedupe.enabled = dedupe_enabled
    deduper = ItemSequenceDeduper()
    polls = []
    for _ in range(2):
        store = RecordingStore()
        run_once(cfg, store, deduper)
        polls.append([p for p in store.points if p[1]["name"] != MACHINE_STATUS_NAME])
    return polls


class Parsing(unittest.TestCase):
    def test_sample_parses_into_points(self):
        points = _sample_points()
        self.assertTrue(points)
        self.assertEqual({p["device_uuid"] for p in points}, {SAMPLE_DEVICE_UUID})
        self.assertLessEqual({p["section"] for p in points}, SECTIONS)


class Processing(unittest.TestCase):
    def test_both_measurements_are_written(self):
        measurements = {m for m, _, _, _ in _process_sample()}
        self.assertEqual(measurements, set(EXPECTED_FIELD))

    def test_points_have_expected_tags_and_field(self):
        for measurement, tags, fields, _ in _process_sample():
            self.assertEqual(set(tags), EXPECTED_TAGS)
            self.assertEqual(set(fields), {EXPECTED_FIELD[measurement]})

    def test_field_types(self):
        for measurement, _, fields, _ in _process_sample():
            value = fields[EXPECTED_FIELD[measurement]]
            self.assertIsInstance(value, float if measurement == METRICS else str)

    def test_numeric_mapping_reaches_metrics(self):
        names = {tags["name"] for m, tags, _, _ in _process_sample() if m == METRICS}
        self.assertIn(KNOWN_METRIC_NAME, names)


class Dedupe(unittest.TestCase):
    def test_repeated_snapshot_is_dropped(self):
        deduper = ItemSequenceDeduper()
        first = deduper.filter(_sample_points())
        second = deduper.filter(_sample_points())
        self.assertTrue(first)
        # Only points without an identity (dataItemId + sequence) may pass twice
        self.assertTrue(all(not p.get("dataItemId") or not p.get("sequence") for p in second))
        self.assertLess(len(second), len(first))

    def test_restarted_agent_is_not_filtered(self):
        deduper = ItemSequenceDeduper()
        points = _sample_points()
        deduper.filter(points)
        # A restarted agent has a new instanceId and numbers its data items from 1 again
        new_instance = str(int(points[0]["instanceId"]) + 1)
        restarted = [dict(p, instanceId=new_instance, sequence=str(i)) for i, p in enumerate(points, 1)]
        self.assertEqual(len(deduper.filter(restarted)), len(restarted))

    def test_enabled_setting_alone_controls_filtering(self):
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                first, second = _poll_sample_twice(enabled)
                self.assertTrue(first)
                # The sample does not change between polls: nothing new to store
                self.assertEqual(len(second), 0 if enabled else len(first))


class Buffering(unittest.TestCase):
    def setUp(self):
        self.target = FlakyStore()
        self.target.error = ConnectionError("database down")

    def test_rows_wait_until_the_store_answers(self):
        store = BufferedStore(self.target, max_rows=10)
        rows = [_status_row("execution", s) for s in range(3)]
        for row in rows:
            store.write_point(*row)
            store.flush()
        self.assertEqual(self.target.points, [])
        self.target.error = None
        store.flush()
        self.assertEqual(self.target.points, rows)

    def test_full_buffer_keeps_the_latest_value_of_every_item(self):
        store = BufferedStore(self.target, max_rows=3)
        program = _status_row("program", 0)
        executions = [_status_row("execution", s) for s in range(1, 5)]
        for row in [program, *executions]:
            store.write_point(*row)
        self.target.error = None
        store.flush()
        # Older executions give way; the only program row and the newest execution stay
        self.assertEqual(self.target.points, [program, *executions[-2:]])

    def test_rejected_rows_are_not_retried(self):
        store = BufferedStore(self.target, max_rows=10)
        self.target.error = RejectedError("bad rows")
        store.write_point(*_status_row("execution", 0))
        store.flush()
        self.target.error = None
        store.flush()
        self.assertEqual(self.target.points, [])


class Placeholders(unittest.TestCase):
    def test_values_come_from_environment(self):
        cfg = _load_config(MTC_AGENT_URL="http://agent:5000/current",
                           INFLUX_URL="http://db:8086", INFLUX_ORG="org",
                           INFLUX_BUCKET="bucket", INFLUX_TOKEN="token")
        self.assertEqual(cfg.ingest.url, "http://agent:5000/current")
        self.assertEqual(cfg.influx.url, "http://db:8086")
        self.assertEqual(cfg.influx.org, "org")
        self.assertEqual(cfg.influx.bucket, "bucket")
        self.assertEqual(cfg.influx.token, "token")

    def test_empty_agent_url_falls_back_to_sample_file(self):
        cfg = _load_config()
        self.assertFalse(cfg.ingest.url)
        self.assertTrue(cfg.ingest.sample_file)


if __name__ == "__main__":
    unittest.main()
