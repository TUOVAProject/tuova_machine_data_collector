from __future__ import annotations
from typing import Any, Dict, Iterable, List, Tuple


class SequenceDeduper:
    """Snapshot deduplication using MTConnect Header lastSequence.

    We keep the latest seen header lastSequence per device and drop points coming from the
    same or older snapshot. This prevents re-inserting the same 'current' page multiple times.
    """

    def __init__(self):
        # device -> last header sequence (int)
        self._last: Dict[str, int] = {}

    @staticmethod
    def _parse_seq(value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(str(value))
        except Exception:
            return None

    def filter(self, points: Iterable[Dict[str, Any]], header_last_sequence: Any) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        dropped = 0
        header_seq = self._parse_seq(header_last_sequence)
        if header_seq is None:
            return list(points)
        for p in points:
            dev = (p.get("device_uuid") or p.get("device_name") or "").strip()
            # If we can't identify a stable key, accept
            if not dev:
                out.append(p)
                continue
            last_seq = self._last.get(dev)
            if last_seq is None or header_seq > last_seq:
                self._last[dev] = header_seq
                out.append(p)
            else:
                dropped += 1
        if dropped:
            print(f"Deduper: dropped {dropped} duplicate-sequence points (header lastSequence)")
        return out


class ItemSequenceDeduper:
    """Per-item deduper using the item's MTConnect sequence number.

    Keyed by (device_uuid|device_name, dataItemId). Drops points whose
    @sequence is equal to or lower than the last seen for that key.
    Falls back to accepting the point when sequence is absent.

    Sequence numbers are comparable only within one agent instance: a restarted
    agent has a new Header instanceId and numbers from the start again, so a
    point from a different instance is always accepted.
    """

    def __init__(self):
        # key -> (agent instanceId, last sequence number)
        self._last: Dict[Tuple[str, str], Tuple[Any, int]] = {}

    @staticmethod
    def _parse_seq(value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(str(value))
        except Exception:
            return None

    def filter(self, points: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        dropped = 0
        for p in points:
            dev = (p.get("device_uuid") or p.get("device_name") or "").strip()
            di = (p.get("dataItemId") or "").strip()
            if not dev or not di:
                out.append(p)
                continue
            seq = self._parse_seq(p.get("sequence"))
            if seq is None:
                out.append(p)
                continue
            key = (dev, di)
            instance = p.get("instanceId")
            last = self._last.get(key)
            if last is not None and last[0] == instance and seq <= last[1]:
                dropped += 1
                continue
            self._last[key] = (instance, seq)
            out.append(p)
        if dropped:
            print(f"Deduper(seq): dropped {dropped} points with same/older sequence")
        return out
