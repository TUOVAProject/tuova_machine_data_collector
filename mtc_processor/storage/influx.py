from __future__ import annotations
from http import HTTPStatus
from typing import Any, Dict, Sequence
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from influxdb_client.rest import ApiException
from ..processors.base import BaseStore, RejectedError, Row


class InfluxStore(BaseStore):
    def __init__(self, url: str, token: str, org: str, bucket: str, verify_ssl: bool = False):
        self.client = InfluxDBClient(url=url, token=token, org=org, verify_ssl=verify_ssl)
        self.write_api = self.client.write_api(write_options=SYNCHRONOUS)
        self.bucket = bucket
        self.org = org

    def write_point(self, measurement: str, tags: Dict[str, str], fields: Dict[str, Any], timestamp: str | None) -> None:
        self.write_points([Row(measurement, tags, fields, timestamp)])

    def write_points(self, rows: Sequence[Row]) -> None:
        """Sends the rows in one request."""
        try:
            self.write_api.write(bucket=self.bucket, org=self.org, record=[self._point(r) for r in rows])
        except ApiException as e:
            # A client error (bad data, no access) stays the same on retry; overload and server errors do not
            if _is_client_error(e.status):
                raise RejectedError(f"InfluxDB rejected {len(rows)} rows: {e.status} {e.reason}") from e
            raise

    @staticmethod
    def _point(row: Row) -> Point:
        p = Point(row.measurement)
        for k, v in row.tags.items():
            if v is not None and v != "":
                p = p.tag(k, v)
        for k, v in row.fields.items():
            p = p.field(k, v)
        if row.timestamp:
            p = p.time(row.timestamp)
        return p

    def flush(self) -> None:
        # Synchronous write flushes per call; nothing extra required.
        pass

    def close(self) -> None:
        self.client.close()


def _is_client_error(status: int | None) -> bool:
    return (status is not None and HTTPStatus.BAD_REQUEST <= status < HTTPStatus.INTERNAL_SERVER_ERROR
            and status != HTTPStatus.TOO_MANY_REQUESTS)
