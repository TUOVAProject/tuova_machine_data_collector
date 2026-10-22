from __future__ import annotations
from typing import Any, Dict, Iterable, List
import xmltodict


def parse_header(xml_str: str) -> Dict[str, Any]:
    """Parse MTConnect Streams Header attributes."""
    doc = xmltodict.parse(xml_str)
    root = doc.get("MTConnectStreams", {})
    header = root.get("Header", {})
    return header or {}


def parse_mtconnect(xml_str: str) -> List[Dict[str, Any]]:
    """Parse MTConnect Streams XML into a flat list of data points.

    Each data point contains:
      - device_name, device_uuid
      - component, component_name
      - element (XML element), name, dataItemId, subType
      - timestamp, sequence
      - creationTime, instanceId (from the Header)
      - value (raw text)
    """
    doc = xmltodict.parse(xml_str)
    root = doc.get("MTConnectStreams", {})
    header = root.get("Header", {})
    creation_time = header.get("@creationTime")
    instance_id = header.get("@instanceId")
    streams = root.get("Streams", {})
    device_streams = streams.get("DeviceStream", [])
    if isinstance(device_streams, dict):
        device_streams = [device_streams]

    datapoints: List[Dict[str, Any]] = []

    for ds in device_streams:
        device_name = ds.get("@name")
        device_uuid = ds.get("@uuid")
        # Iterate ComponentStream(s)
        comps = ds.get("ComponentStream", [])
        if isinstance(comps, dict):
            comps = [comps]
        for comp in comps:
            component = comp.get("@component")
            component_name = comp.get("@name")
            # Sections: Samples, Events, Condition
            for sec_name in ("Samples", "Events", "Condition"):
                sec = comp.get(sec_name)
                if not sec:
                    continue
                # Each child under section might be a dict (single) or list
                for element, entries in sec.items():
                    # Skip XML namespace artifacts if any
                    if element.startswith("@"):  # attributes
                        continue
                    if entries is None:
                        continue
                    if isinstance(entries, list):
                        items = entries
                    else:
                        items = [entries]
                    for it in items:
                        if not isinstance(it, dict):
                            # xmltodict returns value directly sometimes
                            value_text = str(it)
                            it = {"#text": value_text}
                        value = it.get("#text")
                        dp = {
                            "device_name": device_name,
                            "device_uuid": device_uuid,
                            "component": component,
                            "component_name": component_name,
                            "section": sec_name,
                            "element": element.split(":")[-1],  # drop ns prefix
                            "name": it.get("@name"),
                            "dataItemId": it.get("@dataItemId"),
                            "subType": it.get("@subType"),
                            "timestamp": it.get("@timestamp"),
                            "sequence": it.get("@sequence"),
                            "creationTime": creation_time,
                            "instanceId": instance_id,
                            "value": value,
                        }
                        datapoints.append(dp)
    return datapoints


def is_number(s: str | None) -> bool:
    if s is None:
        return False
    try:
        float(s)
        return True
    except Exception:
        return False
