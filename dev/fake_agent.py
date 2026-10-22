"""Simulated MTConnect agent for the test environment (docker-compose.test.yml).

Serves the project's sample XML at /current. On every read a few fields get a
random value, the next sequence number and the current time, like a running
machine; the other data items stay unchanged. Every start is a new agent
instance: a new instanceId and sequence numbers from 1, like a real agent after
the machine has been switched on.

/event makes a one-time change (EVENT_FIELDS), like the machine changing state.
/health answers without changing anything (container healthcheck).
"""
from __future__ import annotations
import json
import os
import random
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Iterator, List

import xmltodict

SAMPLE_FILE = os.getenv("FAKE_AGENT_SAMPLE", "/app/MTConnect-sample/Haas-current.xml")
PORT = 80
CURRENT_PATH = "/current"
EVENT_PATH = "/event"
HEALTH_PATH = "/health"

# Fields that get a new random value on every read: name -> (min, max)
RANDOM_FIELDS = {
    "Cload": (0.0, 100.0),
    "Sload": (0.0, 100.0),
    "Srpm": (0.0, 12000.0),
    "Xload": (0.0, 100.0),
}
# One-time change made by /event: name -> new value (the sample has STOPPED)
EVENT_FIELDS = {
    "execution": "ACTIVE",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _data_items(node: Any) -> Iterator[Dict[str, Any]]:
    """Yields every data item (an element with a sequence number) under node."""
    if isinstance(node, list):
        for child in node:
            yield from _data_items(child)
    elif isinstance(node, dict):
        if "@sequence" in node:
            yield node
            return
        for key, child in node.items():
            if not key.startswith("@"):
                yield from _data_items(child)


class FakeAgent:
    """One agent instance: the sample document and its running sequence number."""

    def __init__(self, sample_xml: str):
        self.doc = xmltodict.parse(sample_xml)
        self.header = self.doc["MTConnectStreams"]["Header"]
        self.items = list(_data_items(self.doc["MTConnectStreams"]["Streams"]))
        self.random_items = self._items_named(RANDOM_FIELDS)
        self.event_items = self._items_named(EVENT_FIELDS)
        self.lock = threading.Lock()
        self.reads = 0
        self.next_sequence = 1
        started = _now()
        for item in self.items:
            self._stamp(item, started)
        self.header["@instanceId"] = str(int(time.time()))
        self.header["@firstSequence"] = "1"

    def _items_named(self, names: Dict[str, Any]) -> List[Dict[str, Any]]:
        found = [it for it in self.items if it.get("@name") in names]
        missing = set(names) - {it["@name"] for it in found}
        if missing:
            raise ValueError(f"Fields not in the sample: {sorted(missing)}")
        return found

    def _stamp(self, item: Dict[str, Any], timestamp: str) -> None:
        item["@sequence"] = str(self.next_sequence)
        item["@timestamp"] = timestamp
        self.next_sequence += 1

    def read(self) -> str:
        """Gives the random fields new values and returns the current document."""
        with self.lock:
            self.reads += 1
            now = _now()
            for item in self.random_items:
                low, high = RANDOM_FIELDS[item["@name"]]
                item["#text"] = f"{random.uniform(low, high):.1f}"
                self._stamp(item, now)
            self.header["@creationTime"] = now
            self.header["@lastSequence"] = str(self.next_sequence - 1)
            self.header["@nextSequence"] = str(self.next_sequence)
            print(f"read {self.reads}: lastSequence={self.next_sequence - 1}", flush=True)
            return xmltodict.unparse(self.doc)

    def event(self) -> None:
        """Changes the event fields once, as the machine would."""
        with self.lock:
            now = _now()
            for item in self.event_items:
                item["#text"] = EVENT_FIELDS[item["@name"]]
                self._stamp(item, now)
                print(f"event: {item['@name']}={item['#text']} sequence={item['@sequence']}", flush=True)

    def status(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "instanceId": self.header["@instanceId"],
                "reads": self.reads,
                "lastSequence": self.next_sequence - 1,
            }


def make_handler(agent: FakeAgent) -> type:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path.startswith(CURRENT_PATH):
                self._send(200, "application/xml", agent.read())
            elif self.path == EVENT_PATH:
                agent.event()
                self._send(200, "application/json", json.dumps(agent.status()))
            elif self.path == HEALTH_PATH:
                self._send(200, "application/json", json.dumps(agent.status()))
            else:
                self._send(404, "text/plain", "not found")

        def _send(self, code: int, content_type: str, body: str) -> None:
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: Any) -> None:
            pass  # reads are printed by FakeAgent.read; healthchecks would only add noise

    return Handler


class AgentServer(ThreadingHTTPServer):
    def handle_error(self, request: Any, client_address: Any) -> None:
        # Typically a collector that gave up waiting (timeout) before the answer
        print(f"request from {client_address[0]} failed: {sys.exc_info()[0].__name__}", flush=True)


def main() -> None:
    with open(SAMPLE_FILE, "r", encoding="utf-8") as f:
        agent = FakeAgent(f.read())
    print(
        f"Fake agent started: instanceId={agent.header['@instanceId']}, "
        f"{len(agent.items)} data items, random fields: {', '.join(RANDOM_FIELDS)}",
        flush=True,
    )
    AgentServer(("", PORT), make_handler(agent)).serve_forever()


if __name__ == "__main__":
    main()
