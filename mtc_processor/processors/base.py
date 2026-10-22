from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict, Iterable, NamedTuple, Optional, Sequence
import logging

from ..logutil import get_processor_logger


class Row(NamedTuple):
    """One row to store: the arguments of BaseStore.write_point."""
    measurement: str
    tags: Dict[str, str]
    fields: Dict[str, Any]
    timestamp: str | None


class RejectedError(Exception):
    """The store refused the rows for good: sending them again would not help."""


class BaseStore(ABC):
    @abstractmethod
    def write_point(self, measurement: str, tags: Dict[str, str], fields: Dict[str, Any], timestamp: str | None) -> None: ...

    def write_points(self, rows: Sequence[Row]) -> None:
        """Writes several rows; stores that can send a batch at once override this."""
        for row in rows:
            self.write_point(*row)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


class BaseProcessor(ABC):
    name: str = "base"
    _logger: Optional[logging.Logger] = None

    @property
    def logger(self) -> logging.Logger:
        if self._logger is None:
            self._logger = get_processor_logger(self.name)
        return self._logger

    @abstractmethod
    def process(self, points: Iterable[Dict[str, Any]], store: "BaseStore") -> None:  # noqa: F821
        ...

