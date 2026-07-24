from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from collections.abc import Callable, Sequence
from typing import Mapping

DAY_SECONDS = 24 * 60 * 60
TOPOLOGY_MAX_AGE = 7 * DAY_SECONDS
CACHE_TTL = 90 * DAY_SECONDS
FULL_REFRESH_COOLDOWN = 10 * 60
UNIT_LOCK_TTL = 30
REDIS_TIMEOUT = 2.0
CIRCUIT_BREAKER_SECONDS = 60.0
UNIT_STATUSES = frozenset({"info", "empty", "error"})


@dataclass(frozen=True)
class Snapshot:
    payload: dict
    orphan_fields: tuple[str, ...] = ()


class CacheUnavailable(RuntimeError):
    pass


def _rest_pipeline(url: str, token: str, commands: Sequence[Sequence[object]],
                   timeout: float) -> list[object]:
    body = json.dumps(commands, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        url.rstrip("/") + "/pipeline",
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        decoded = json.loads(response.read().decode("utf-8"))
    if not isinstance(decoded, list) or len(decoded) != len(commands):
        raise CacheUnavailable("Redis pipeline 응답 형식이 올바르지 않습니다.")
    values = []
    for item in decoded:
        if not isinstance(item, dict) or "error" in item:
            raise CacheUnavailable("Redis 명령 실행에 실패했습니다.")
        values.append(item.get("result"))
    return values


class UpstashTransport:
    def __init__(self, url: str, token: str,
                 request: Callable = _rest_pipeline,
                 monotonic: Callable[[], float] = time.monotonic):
        self.url = url
        self._token = token
        self._request = request
        self._monotonic = monotonic
        self._disabled_until = 0.0

    def pipeline(self, commands: Sequence[Sequence[object]]) -> list[object]:
        now = self._monotonic()
        if now < self._disabled_until:
            raise CacheUnavailable("Redis 회로 차단기가 열려 있습니다.")
        try:
            return self._request(self.url, self._token, commands, REDIS_TIMEOUT)
        except CacheUnavailable:
            self._disabled_until = self._monotonic() + CIRCUIT_BREAKER_SECONDS
            raise
        except Exception as error:
            self._disabled_until = self._monotonic() + CIRCUIT_BREAKER_SECONDS
            raise CacheUnavailable("Redis에 연결할 수 없습니다.") from error


def _part(value: object, limit: int = 64) -> str:
    text = str(value)
    if not text or len(text) > limit or any(ord(char) < 32 for char in text):
        raise ValueError("올바르지 않은 캐시 식별자입니다.")
    return urllib.parse.quote(text, safe="")


def complex_key(hm: str, pb: str) -> str:
    return f"scan:v1:{_part(hm, 32)}:{_part(pb, 32)}"


def topology_field(sn: object) -> str:
    return f"t:{_part(sn, 32)}"


def unit_field(dong: str, ho: str) -> str:
    return f"u:{_part(dong)}:{_part(ho)}"


def _load_fields(raw: Mapping[str, str]) -> tuple[dict[str, dict], set[str]]:
    loaded = {}
    broken = set()
    for field, value in raw.items():
        try:
            item = json.loads(value)
            if not isinstance(item, dict):
                raise ValueError("필드 값이 객체가 아닙니다.")
            loaded[field] = item
        except (TypeError, ValueError, json.JSONDecodeError):
            broken.add(field)
    return loaded, broken


def _refresh_due(unit: dict, now: int) -> bool:
    last_error_at = int(unit.get("last_error_at") or 0)
    if last_error_at:
        return now - last_error_at >= DAY_SECONDS
    if unit.get("status") == "info":
        return now - int(unit.get("checked_at") or 0) >= TOPOLOGY_MAX_AGE
    if unit.get("status") in {"empty", "error"}:
        return now - int(unit.get("checked_at") or 0) >= DAY_SECONDS
    return False


def assemble_snapshot(raw: Mapping[str, str], now: int) -> Snapshot:
    refresh = {"topology": True, "supply": True, "all_units": True, "units": []}
    if not raw:
        return Snapshot({"cache": "miss", "complete": False, "checked_at": None,
                         "meta": None, "units": [], "refresh": refresh})

    fields, broken = _load_fields(raw)
    dongs_record = fields.get("_dongs")
    if not dongs_record or not isinstance(dongs_record.get("dongs"), list):
        return Snapshot({"cache": "partial", "complete": False, "checked_at": None,
                         "meta": None, "units": [], "refresh": refresh},
                        tuple(sorted(field for field in broken if field.startswith("u:"))))

    dongs = dongs_record["dongs"]
    topology_checked_at = int(dongs_record.get("checked_at") or 0)
    topology_complete = True
    meta_dongs = []
    expected = []
    timestamps = [topology_checked_at]
    for dong in dongs:
        record = fields.get(topology_field(dong["sn"]))
        if not record or int(record.get("checked_at") or 0) < topology_checked_at:
            topology_complete = False
            continue
        hos = [str(ho) for ho in record.get("hos", [])]
        meta_dongs.append({"name": str(dong["name"]), "hos": hos,
                           "grid": record.get("grid")})
        expected.extend((str(dong["name"]), ho) for ho in hos)
        timestamps.append(int(record["checked_at"]))

    expected_fields = {unit_field(dong, ho): (dong, ho) for dong, ho in expected}
    units = []
    missing = []
    due = []
    for field, (dong, ho) in expected_fields.items():
        unit = fields.get(field)
        if not unit or unit.get("status") not in UNIT_STATUSES:
            missing.append({"dong": dong, "ho": ho})
            continue
        units.append(unit)
        timestamps.append(int(unit.get("checked_at") or 0))
        if _refresh_due(unit, now):
            due.append({"dong": dong, "ho": ho})

    orphan_fields = tuple(sorted(
        field for field in fields
        if field.startswith("u:") and field not in expected_fields
    )) if topology_complete else ()
    supply_record = fields.get("_supply")
    supply = supply_record.get("supply") if supply_record else None
    supply_checked_at = int(supply_record.get("checked_at") or 0) if supply_record else 0
    full_topology_due = bool(dongs) and now - topology_checked_at >= TOPOLOGY_MAX_AGE
    topology_due = (not topology_complete or
                    (not dongs and now - topology_checked_at >= DAY_SECONDS) or
                    full_topology_due)
    all_units = topology_complete and full_topology_due
    supply_due = (supply_record is None or
                  (supply is None and now - supply_checked_at >= DAY_SECONDS) or
                  full_topology_due)
    complete = topology_complete and not missing
    refresh = {"topology": topology_due, "supply": supply_due,
               "all_units": all_units, "units": missing + due}
    if not complete:
        cache_state = "partial"
    elif topology_due or supply_due or all_units or due:
        cache_state = "stale"
    else:
        cache_state = "fresh"
    payload = {
        "cache": cache_state,
        "complete": complete,
        "checked_at": min(timestamps) if timestamps else None,
        "meta": {"total": len(expected), "dongs": meta_dongs, "supply": supply},
        "units": units,
        "refresh": refresh,
    }
    return Snapshot(payload, orphan_fields)


class CacheStore:
    def __init__(self, transport, now: Callable[[], int] = lambda: int(time.time())):
        self.transport = transport
        self.now = now

    @classmethod
    def from_env(cls, environ=None):
        values = os.environ if environ is None else environ
        url = values.get("UPSTASH_REDIS_REST_URL")
        token = values.get("UPSTASH_REDIS_REST_TOKEN")
        if not (url and token):
            return None
        return cls(UpstashTransport(url, token))

    @staticmethod
    def _hash(result) -> dict[str, str]:
        if result is None:
            return {}
        if isinstance(result, dict):
            return {str(key): str(value) for key, value in result.items()}
        if not isinstance(result, list) or len(result) % 2:
            raise CacheUnavailable("HGETALL 응답 형식이 올바르지 않습니다.")
        return {str(result[index]): str(result[index + 1])
                for index in range(0, len(result), 2)}

    def read_snapshot(self, hm: str, pb: str, request_full: bool = False) -> dict:
        key = complex_key(hm, pb)
        try:
            result = self.transport.pipeline([["HGETALL", key], ["EXPIRE", key, CACHE_TTL]])
            snapshot = assemble_snapshot(self._hash(result[0]), self.now())
            if snapshot.orphan_fields:
                try:
                    self.transport.pipeline([["HDEL", key, *snapshot.orphan_fields],
                                             ["EXPIRE", key, CACHE_TTL]])
                except CacheUnavailable:
                    pass
            return snapshot.payload
        except (CacheUnavailable, ValueError):
            return {"cache": "disabled", "complete": False, "checked_at": None,
                    "meta": None, "units": [],
                    "refresh": {"topology": True, "supply": True,
                                "all_units": True, "units": []},
                    "full_refresh": {"allowed": True, "retry_after": 0}}

    def _write(self, hm: str, pb: str, field: str, value: dict) -> bool:
        saved = dict(value)
        saved["checked_at"] = int(saved.get("checked_at") or self.now())
        key = complex_key(hm, pb)
        try:
            self.transport.pipeline([
                ["HSET", key, field, json.dumps(saved, ensure_ascii=False,
                                                  separators=(",", ":"))],
                ["EXPIRE", key, CACHE_TTL],
            ])
            return True
        except (CacheUnavailable, ValueError):
            return False

    def write_dongs(self, hm, pb, dongs):
        return self._write(hm, pb, "_dongs", {"dongs": dongs})

    def write_hos(self, hm, pb, sn, hos, grid):
        return self._write(hm, pb, topology_field(sn), {"sn": sn, "hos": hos, "grid": grid})

    def write_supply(self, hm, pb, supply):
        return self._write(hm, pb, "_supply", {"supply": supply})

    def write_unit(self, hm, pb, unit):
        clean = {key: value for key, value in unit.items()
                 if key in {"dong", "ho", "status", "fields"}}
        return self._write(hm, pb, unit_field(clean["dong"], clean["ho"]), clean)
