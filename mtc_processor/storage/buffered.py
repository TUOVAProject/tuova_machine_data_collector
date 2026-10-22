from __future__ import annotations
from collections import Counter, deque
from itertools import islice
from typing import Any, Deque, Dict, Tuple

from ..processors.base import BaseStore, RejectedError, Row

# InfluxDB's recommended batch size; a long backlog is sent in pieces of this size
WRITE_BATCH_ROWS = 5000


def _series(row: Row) -> Tuple[str, frozenset]:
    """The data item a row belongs to: its measurement and tags."""
    return row.measurement, frozenset(row.tags.items())


class BufferedStore(BaseStore):
    """Keeps rows until the target store has accepted them.

    Rows are sent on flush(). While the target cannot be reached they wait for
    the next flush, at most max_rows of them. When the buffer is full, the oldest
    row that already has a newer row of the same data item waiting is dropped
    first, so the latest value of every item survives a long outage.
    """

    def __init__(self, target: BaseStore, max_rows: int):
        self.target = target
        self.max_rows = max_rows
        self._rows: Deque[Row] = deque()
        # series -> number of its rows waiting
        self._waiting: Counter = Counter()
        self._unreachable = False
        self._dropped = 0

    def write_point(self, measurement: str, tags: Dict[str, str], fields: Dict[str, Any], timestamp: str | None) -> None:
        row = Row(measurement, tags, fields, timestamp)
        self._rows.append(row)
        self._waiting[_series(row)] += 1
        if len(self._rows) > self.max_rows:
            self._drop_one()

    def _drop_one(self) -> None:
        index = next((i for i, row in enumerate(self._rows) if self._waiting[_series(row)] > 1), 0)
        row = self._rows[index]
        del self._rows[index]
        self._forget(row)
        self._dropped += 1

    def _forget(self, row: Row) -> None:
        key = _series(row)
        self._waiting[key] -= 1
        if not self._waiting[key]:
            del self._waiting[key]

    def flush(self) -> None:
        while self._rows:
            batch = list(islice(self._rows, WRITE_BATCH_ROWS))
            try:
                self.target.write_points(batch)
            except RejectedError as e:
                print(f"Store: dropped {len(batch)} rejected rows: {e}")
            except Exception as e:
                self._unreachable = True
                print(f"Store unreachable, {len(self._rows)} rows waiting ({self._dropped} dropped): {e}")
                return
            for _ in batch:
                self._forget(self._rows.popleft())
        if self._unreachable:
            print(f"Store reachable again: waiting rows written ({self._dropped} dropped)")
            self._unreachable = False
            self._dropped = 0
        self.target.flush()

    def close(self) -> None:
        self.flush()
        if self._rows:
            print(f"Store: {len(self._rows)} rows not written")
        self.target.close()
