from __future__ import annotations
from typing import Any, Dict, Iterable, Optional

from .base import BaseProcessor, BaseStore
from ..transform import is_number


class MetricsProcessor(BaseProcessor):
    name = "metrics"

    def __init__(self, numeric_elements: list[str], status_elements: Optional[list[str]] = None):
        # Normalize to lowercase for comparisons against the MTConnect ``name`` attribute.
        self.numeric_filters = {item.lower() for item in (numeric_elements or [])}
        self.status_filters = {item.lower() for item in (status_elements or [])}

    def process(self, points: Iterable[Dict[str, Any]], store: BaseStore) -> None:
        # Log diagnostics to file (not console) for input shape
        try:
            length_info = f", length={len(points)}"  # may fail for generators
        except Exception:
            length_info = ""
        self.logger.debug(
            "Received points iterable type=%s%s",
            type(points).__name__,
            length_info,
        )

        first_reported = False
        for p in points:
            if not first_reported:
                try:
                    keys = list(p.keys()) if isinstance(p, dict) else []
                    self.logger.debug(
                        "First point type=%s; keys=%s; value_field_type=%s",
                        type(p).__name__,
                        keys,
                        (type(p.get("value")).__name__ if isinstance(p, dict) and "value" in p else "n/a"),
                    )
                except Exception as e:
                    self.logger.debug("Failed to summarize first point: %s", e)
                first_reported = True
            section = (p.get("section") or "").lower()
            element_name = (p.get("element") or "").lower()
            point_name = (p.get("name") or "").lower()
            filter_key = point_name
            value = p.get("value")
            value_is_number = is_number(value)
            tags = {
                "device": p.get("device_uuid") or p.get("device_name") or "unknown",
                "component": (p.get("component_name") or p.get("component") or "").lower(),
                "element": element_name,
                "name": point_name,
            }
            timestamp = p.get("timestamp")
            sequence = p.get("sequence")

            display_value = value
            if (display_value is None or display_value == "") and element_name:
                display_value = element_name

            self.logger.info(
                "Processing point name=%s element=%s component=%s value=%s timestamp=%s sequence=%s",
                point_name or element_name or "",
                element_name,
                tags["component"],
                display_value,
                timestamp,
                sequence,
            )

            if section in ("events", "condition"):
                self.logger.info(
                    "Status raw -> tags=%s value=%s timestamp=%s sequence=%s",
                    tags,
                    display_value,
                    timestamp,
                    sequence,
                )

            # Numeric metrics branch
            if filter_key in self.numeric_filters and value_is_number:
                fields = {"value": float(value)}
                self.logger.debug(
                    "Metric point -> tags=%s fields=%s timestamp=%s sequence=%s",
                    tags,
                    fields,
                    timestamp,
                    sequence,
                )
                store.write_point("mtc_metrics", tags, fields, timestamp)

            # Status branch (explicit list or implicit non-numeric values)
            status_candidate = (filter_key in self.status_filters) or (not value_is_number)
            if status_candidate:
                state_value = value
                if state_value is None or state_value == "":
                    state_value = element_name or point_name or "unknown"
                state = str(state_value)
                fields = {"state": state}
                self.logger.info(
                    "Status point -> tags=%s state=%s timestamp=%s sequence=%s",
                    tags,
                    state,
                    timestamp,
                    sequence,
                )
                store.write_point("mtc_status", tags, fields, timestamp)
        store.flush()

