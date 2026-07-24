from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
import uuid
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


@dataclass(frozen=True)
class LockResult:
    state: str
    token: str | None = None


class CacheUnavailable(RuntimeError):
    pass


_RELEASE_SCRIPT = (
    'if redis.call("get", KEYS[1]) == ARGV[1] then '
    'return redis.call("del", KEYS[1]) else return 0 end'
)
_WRITE_UNIT_SCRIPT = (
    'if redis.call("get", KEYS[1]) ~= ARGV[1] then return 0 end '
    'redis.call("hset", KEYS[2], ARGV[2], ARGV[3]) '
    'redis.call("expire", KEYS[2], ARGV[4]) '
    'return 1'
)


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
        if not isinstance(item, dict) or "error" in item or "result" not in item:
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


def _unit_lock_key(hm, pb, dong, ho):
    return f"lock:{complex_key(hm, pb)}:{_part(dong)}:{_part(ho)}"


def _full_refresh_key(hm, pb):
    return f"cooldown:{complex_key(hm, pb)}:full"


def _decode_record(value) -> dict | None:
    try:
        record = json.loads(value) if value is not None else None
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return record if isinstance(record, dict) else None


def _timestamp(value, now: int) -> int | None:
    if type(value) is not int or value <= 0 or value > now:
        return None
    return value


def _text_identifier(value, limit: int = 64) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        _part(value, limit)
    except ValueError:
        return None
    return value


def _valid_serial(value) -> bool:
    return type(value) is int and value > 0 and len(str(value)) <= 32


def _normalize_dongs(record: dict | None, now: int) -> dict | None:
    if record is None or not isinstance(record.get("dongs"), list):
        return None
    checked_at = _timestamp(record.get("checked_at"), now)
    if checked_at is None:
        return None
    dongs = []
    serials = set()
    names = set()
    for item in record["dongs"]:
        if not isinstance(item, dict):
            return None
        serial = item.get("sn")
        name = _text_identifier(item.get("name"))
        if not _valid_serial(serial) or name is None:
            return None
        if serial in serials or name in names:
            return None
        serials.add(serial)
        names.add(name)
        dongs.append({"sn": serial, "name": name})
    return {"dongs": dongs, "checked_at": checked_at}


def _normalize_grid(value, hos: list[str]) -> dict | None | bool:
    if value is None:
        return None
    if not isinstance(value, dict):
        return False
    floors = value.get("floors")
    lines = value.get("lines")
    cells = value.get("cells")
    if not isinstance(floors, list) or not isinstance(lines, list) or not isinstance(cells, dict):
        return False
    if (any(type(floor) is not int for floor in floors)
            or any(_text_identifier(line) is None for line in lines)):
        return False
    if len(set(floors)) != len(floors) or len(set(lines)) != len(lines):
        return False
    if set(cells) != set(hos):
        return False
    normalized_cells = {}
    cell_floors = set()
    cell_lines = set()
    for ho, position in cells.items():
        if (not isinstance(position, list) or len(position) != 2
                or type(position[0]) is not int
                or _text_identifier(position[1]) is None):
            return False
        floor, line = position
        if floor not in floors or line not in lines:
            return False
        normalized_cells[ho] = [floor, line]
        cell_floors.add(floor)
        cell_lines.add(line)
    if cell_floors != set(floors) or cell_lines != set(lines):
        return False
    return {"floors": list(floors), "lines": list(lines), "cells": normalized_cells}


def _normalize_topology(record: dict | None, now: int, serial: int) -> dict | None:
    if (record is None or not _valid_serial(record.get("sn"))
            or record.get("sn") != serial or not isinstance(record.get("hos"), list)):
        return None
    checked_at = _timestamp(record.get("checked_at"), now)
    if checked_at is None:
        return None
    hos = []
    for value in record["hos"]:
        ho = _text_identifier(value)
        if ho is None or ho in hos:
            return None
        hos.append(ho)
    grid = _normalize_grid(record.get("grid"), hos)
    if grid is False:
        return None
    return {"sn": serial, "hos": hos, "grid": grid, "checked_at": checked_at}


_SUPPLY_TEXT_FIELDS = ("type", "short", "net_area", "area")
_SUPPLY_COUNT_FIELDS = ("general", "special", "total")


def _normalize_supply(record: dict | None, now: int) -> dict | None:
    if record is None:
        return None
    checked_at = _timestamp(record.get("checked_at"), now)
    supply = record.get("supply")
    if checked_at is None or (supply is not None and not isinstance(supply, list)):
        return None
    if supply is None:
        return {"supply": None, "checked_at": checked_at}
    normalized = []
    types = set()
    for item in supply:
        if not isinstance(item, dict):
            return None
        if any(not isinstance(item.get(field), str) for field in _SUPPLY_TEXT_FIELDS):
            return None
        if any(type(item.get(field)) is not int or item[field] < 0
               for field in _SUPPLY_COUNT_FIELDS):
            return None
        if not item["type"] or item["type"] in types:
            return None
        types.add(item["type"])
        normalized.append({
            field: item[field]
            for field in (*_SUPPLY_TEXT_FIELDS, *_SUPPLY_COUNT_FIELDS)
        })
    return {"supply": normalized, "checked_at": checked_at}


def _normalize_unit(record: dict | None, now: int, dong: str, ho: str) -> dict | None:
    if record is None or record.get("dong") != dong or record.get("ho") != ho:
        return None
    status = record.get("status")
    fields = record.get("fields")
    checked_at = _timestamp(record.get("checked_at"), now)
    if (not isinstance(status, str) or status not in UNIT_STATUSES
            or not isinstance(fields, dict) or checked_at is None):
        return None
    if any(not isinstance(key, str) or not isinstance(value, str)
           for key, value in fields.items()):
        return None
    normalized = {
        "dong": dong,
        "ho": ho,
        "status": status,
        "fields": dict(fields),
        "checked_at": checked_at,
    }
    if "last_error_at" in record:
        last_error_at = _timestamp(record.get("last_error_at"), now)
        if last_error_at is None:
            return None
        normalized["last_error_at"] = last_error_at
        if "last_error" in record:
            if record.get("last_error") != "최근 갱신에 실패했습니다.":
                return None
            normalized["last_error"] = "최근 갱신에 실패했습니다."
    elif "last_error" in record:
        return None
    return normalized


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

    dongs_record = _normalize_dongs(_decode_record(raw.get("_dongs")), now)
    if dongs_record is None:
        return Snapshot({"cache": "partial", "complete": False, "checked_at": None,
                         "meta": None, "units": [], "refresh": refresh})

    dongs = dongs_record["dongs"]
    topology_checked_at = int(dongs_record.get("checked_at") or 0)
    topology_complete = True
    meta_dongs = []
    expected = []
    timestamps = [topology_checked_at]
    for dong in dongs:
        record = _normalize_topology(
            _decode_record(raw.get(topology_field(dong["sn"]))), now, dong["sn"],
        )
        if record is None or record["checked_at"] < topology_checked_at:
            topology_complete = False
            continue
        hos = record["hos"]
        meta_dongs.append({"name": dong["name"], "hos": hos,
                           "grid": record.get("grid")})
        expected.extend((dong["name"], ho) for ho in hos)
        timestamps.append(int(record["checked_at"]))

    expected_fields = {unit_field(dong, ho): (dong, ho) for dong, ho in expected}
    units = []
    missing = []
    due = []
    for field, (dong, ho) in expected_fields.items():
        unit = _normalize_unit(_decode_record(raw.get(field)), now, dong, ho)
        if unit is None:
            missing.append({"dong": dong, "ho": ho})
            continue
        units.append(unit)
        timestamps.append(int(unit.get("checked_at") or 0))
        if _refresh_due(unit, now):
            due.append({"dong": dong, "ho": ho})

    orphan_fields = tuple(sorted(
        field for field in raw
        if field.startswith("u:") and field not in expected_fields
    )) if topology_complete else ()
    supply_record = _normalize_supply(_decode_record(raw.get("_supply")), now)
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

    def _write_unit(self, hm, pb, dong, ho, value, token):
        if not token:
            return False
        saved = dict(value)
        saved["checked_at"] = int(saved.get("checked_at") or self.now())
        key = complex_key(hm, pb)
        try:
            result = self.transport.pipeline([[
                "EVAL", _WRITE_UNIT_SCRIPT, 2,
                _unit_lock_key(hm, pb, dong, ho), key,
                token, unit_field(dong, ho),
                json.dumps(saved, ensure_ascii=False, separators=(",", ":")),
                CACHE_TTL,
            ]])[0]
            return bool(result)
        except (CacheUnavailable, ValueError):
            return False

    def write_unit(self, hm, pb, unit, token):
        clean = {key: value for key, value in unit.items()
                 if key in {"dong", "ho", "status", "fields"}}
        if clean.get("status") not in UNIT_STATUSES:
            return False
        return self._write_unit(
            hm, pb, clean["dong"], clean["ho"], clean, token,
        )

    def claim_unit(self, hm, pb, dong, ho, token=None):
        owner = token or uuid.uuid4().hex
        try:
            result = self.transport.pipeline([[
                "SET", _unit_lock_key(hm, pb, dong, ho), owner,
                "NX", "EX", UNIT_LOCK_TTL,
            ]])[0]
        except (CacheUnavailable, ValueError):
            return LockResult("unavailable")
        return LockResult("acquired", owner) if result == "OK" else LockResult("busy")

    def release_unit(self, hm, pb, dong, ho, token):
        try:
            result = self.transport.pipeline([[
                "EVAL", _RELEASE_SCRIPT, 1,
                _unit_lock_key(hm, pb, dong, ho), token,
            ]])[0]
            return bool(result)
        except (CacheUnavailable, ValueError):
            return False

    def claim_full_refresh(self, hm, pb):
        key = _full_refresh_key(hm, pb)
        token = uuid.uuid4().hex
        try:
            for _ in range(2):
                result, ttl = self.transport.pipeline([
                    ["SET", key, token, "NX", "EX", FULL_REFRESH_COOLDOWN],
                    ["TTL", key],
                ])
                if result == "OK":
                    return {"allowed": True, "retry_after": 0}
                retry_after = max(int(ttl or 0), 0)
                if retry_after:
                    return {"allowed": False, "retry_after": retry_after}
            return {"allowed": True, "retry_after": 0}
        except (CacheUnavailable, ValueError):
            return {"allowed": True, "retry_after": 0}

    def read_unit(self, hm, pb, dong, ho):
        try:
            result = self.transport.pipeline([[
                "HGET", complex_key(hm, pb), unit_field(dong, ho),
            ]])[0]
            return _normalize_unit(_decode_record(result), self.now(), dong, ho)
        except (CacheUnavailable, ValueError):
            return None

    def record_unit_error(self, hm, pb, dong, ho, message, token):
        prior = self.read_unit(hm, pb, dong, ho)
        if prior and prior.get("status") in {"info", "empty"}:
            saved = dict(prior)
            saved["last_error_at"] = self.now()
            saved["last_error"] = "최근 갱신에 실패했습니다."
            self._write_unit(hm, pb, dong, ho, saved, token)
            return saved
        saved = {"dong": dong, "ho": ho, "status": "error", "fields": {}}
        saved["checked_at"] = self.now()
        self._write_unit(hm, pb, dong, ho, saved, token)
        return saved
