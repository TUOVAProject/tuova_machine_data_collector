from __future__ import annotations
import os
import yaml
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class IngestConfig:
    url: Optional[str] = None  # e.g., http://ingest_server:9000/mtconnect/current
    timeout_seconds: float = 5.0
    # Optional local fallback file for testing
    sample_file: Optional[str] = None


@dataclass
class InfluxConfig:
    enabled: bool = False
    url: str = "http://influxdb:8086"
    org: str = "tuova"
    bucket: str = "mtc"
    token: Optional[str] = None
    # Rows kept in memory (about 1 KB each) while InfluxDB cannot be reached
    buffer_max_rows: int = 50000


@dataclass
class DedupeConfig:
    enabled: bool = True
    # Drop entire snapshot duplicates using MTConnect Header.lastSequence
    snapshot_creation_time: bool = True


@dataclass
class MetricMapping:
    # Basic rules to group by components/elements
    numeric_elements: List[str] = field(default_factory=lambda: [
        "RotaryVelocity", "AngularVelocity", "Load", "Temperature",
        "AxisFeedrate", "PathFeedrate", "Position", "Angle",
    ])
    status_elements: List[str] = field(default_factory=lambda: [
        "Availability", "EmergencyStop", "Execution", "ControllerMode",
        "DoorState", "Program", "ProgramComment", "FunctionalMode",
        "RotaryMode", "PartCount", "Line",
    ])


@dataclass
class AppConfig:
    device_name: Optional[str] = None
    device_uuid: Optional[str] = None
    ingest: IngestConfig = field(default_factory=IngestConfig)
    influx: InfluxConfig = field(default_factory=InfluxConfig)
    dedupe: DedupeConfig = field(default_factory=DedupeConfig)
    mapping: MetricMapping = field(default_factory=MetricMapping)

    @staticmethod
    def load(path: str) -> "AppConfig":
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        ingest_cfg = IngestConfig(**(data.get("ingest", {}) or {}))
        influx_cfg = InfluxConfig(**(data.get("influx", {}) or {}))
        # ${VAR} placeholders let one YAML serve every environment; values come from env
        _resolve_fields(ingest_cfg, ("url", "sample_file"))
        _resolve_fields(influx_cfg, ("url", "org", "bucket"))
        # Resolve env placeholder for token, or fall back to INFLUX_TOKEN env var if missing
        influx_cfg.token = _resolve_env_placeholder(influx_cfg.token) or os.getenv("INFLUX_TOKEN", influx_cfg.token)

        return AppConfig(
            device_name=data.get("device_name"),
            device_uuid=data.get("device_uuid"),
            ingest=ingest_cfg,
            influx=influx_cfg,
            dedupe=DedupeConfig(**(data.get("dedupe", {}) or {})),
            mapping=MetricMapping(**(data.get("mapping", {}) or {})),
        )

    @staticmethod
    def from_env(default_path: str = "/app/config/mtc_config.yaml") -> "AppConfig":
        path = os.getenv("MTC_CONFIG", default_path)
        return AppConfig.load(path)


def _resolve_fields(section: Any, names: tuple[str, ...]) -> None:
    """Resolve env placeholders in the named attributes of a config section, in place."""
    for name in names:
        setattr(section, name, _resolve_env_placeholder(getattr(section, name)))


def _resolve_env_placeholder(value: Optional[str]) -> Optional[str]:
    """Resolve values like ${VAR} or ${VAR:-default} from environment.

    Returns the resolved string, empty string if explicitly defaulted to empty,
    or None if value was None.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not (s.startswith("${") and s.endswith("}")):
        return s
    inner = s[2:-1]
    if ":-" in inner:
        var, default = inner.split(":-", 1)
        return os.getenv(var, default)
    return os.getenv(inner, "")
