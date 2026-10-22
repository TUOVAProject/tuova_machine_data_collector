from __future__ import annotations
from typing import Any, Dict
from ..processors.base import BaseStore


class DryRunStore(BaseStore):
    def __init__(self, limit: int | None = 10):
        self.count = 0
        self.limit = limit

    def write_point(self, measurement: str, tags: Dict[str, str], fields: Dict[str, Any], timestamp: str | None) -> None:
        if self.limit is None or self.count < self.limit:
            print(f"[DRYRUN] {measurement} tags={tags} fields={fields} ts={timestamp}")
        self.count += 1

    def flush(self) -> None:
        # One store serves every poll: print the first rows of each poll
        self.count = 0
