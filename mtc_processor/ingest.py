from __future__ import annotations
import requests
from typing import Optional


class IngestClient:
    def __init__(self, base_url: Optional[str], timeout_seconds: float = 5.0, sample_file: Optional[str] = None):
        self.base_url = base_url
        self.timeout = timeout_seconds
        self.sample_file = sample_file

    def get_current_xml(self) -> str:
        """Fetch MTConnect current XML from ingest server or from sample file."""
        if self.base_url:
            url = self.base_url.rstrip("/")
            resp = requests.get(url, timeout=self.timeout)
            resp.raise_for_status()
            return resp.text
        if self.sample_file:
            with open(self.sample_file, "r", encoding="utf-8") as f:
                return f.read()
        raise RuntimeError("No ingest URL or sample file configured")
