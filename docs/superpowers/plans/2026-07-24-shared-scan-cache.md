# Shared Scan Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upstash Redis에 단지별 최신 스캔 결과를 저장해 모든 방문자가 공유하고, 저장된 결과를 먼저 표시한 뒤 필요한 항목만 재조회한다.

**Architecture:** `api/_cache.py`가 Upstash REST transport, Redis Hash 스키마, 최신성 판정, TTL과 잠금을 소유한다. 기존 Python API는 청약홈에서 직접 받은 결과를 write-through하고, 새 `/api/cache`는 조립된 스냅샷과 서버가 계산한 refresh 계획을 반환한다. 브라우저는 순수 헬퍼 모듈의 refresh 계획을 실행해 캐시 결과와 새 결과를 기존 화면·CSV 상태에 합친다.

**Tech Stack:** Python 3.12+ 표준 라이브러리, Vercel Python Functions, Upstash Redis REST API, vanilla JavaScript ES modules, Node.js built-in test runner, Python `unittest`

## Global Constraints

- `UPSTASH_REDIS_REST_URL`과 `UPSTASH_REDIS_REST_TOKEN`은 Python API에서만 읽고 브라우저·응답·로그에 노출하지 않는다.
- 새 Python 런타임 의존성을 추가하지 않는다. REST 호출은 `urllib.request`를 사용한다.
- Redis 미설정·장애·한도 초과 시 기존 직접 스캔으로 fail-open한다.
- 호실 상태는 `info`, `empty`, `error`만 사용하고 날짜별 이력은 저장하지 않는다.
- `empty`·`error`는 24시간, 완전한 topology와 `info`는 7일, 단지 Hash는 마지막 접근부터 90일, 전체 새로고침 cooldown은 10분이다.
- 호실 잠금 TTL은 30초, Redis REST timeout은 2초, warm-instance 회로 차단기는 60초다.
- 브라우저의 청약홈 요청 동시성은 기존 `CONCURRENCY = 3`을 유지한다.
- 브라우저는 캐시 데이터를 쓰지 않는다. 기존 서버 API가 직접 확인한 결과만 Redis에 저장한다.
- 캐시 정책과 시각 판정은 서버에만 두고 브라우저는 `/api/cache` 응답의 `refresh` 지시만 실행한다.
- 로컬 `python3 app.py`와 Vercel 배포본은 같은 API 로직과 정적 파일을 사용한다.

## File Structure

| 파일 | 책임 |
|---|---|
| `api/_cache.py` | Upstash REST transport, 키 스키마, 스냅샷 조립, TTL, 잠금, cooldown, 오류 보존 |
| `api/cache.py` | `GET /api/cache` Vercel 진입점 |
| `api/_lib.py` | `/api/cache` 순수 라우트와 기존 API write-through·호실 잠금 통합 |
| `public/cache.mjs` | 브라우저 상태 병합, refresh 작업 선택, 공유 결과 polling 순수 함수 |
| `public/index.html` | 캐시 우선 조회, 부분 갱신, 상태 문구, 전체 새로고침 UI |
| `server.py` | 로컬 `/cache.mjs` 정적 파일 서빙 |
| `tests/test_cache.py` | Redis transport와 캐시 정책 단위 테스트 |
| `tests/test_api.py` | write-through, 잠금 응답, `/api/cache` 계약 테스트 |
| `tests/test_server_search.py` | 로컬 `/api/cache`와 `/cache.mjs` 라우팅 테스트 |
| `tests/test_frontend_cache.mjs` | 프런트엔드 순수 헬퍼 Node 테스트 |
| `README.md` | Upstash 연결, 갱신 정책, 장애 시 동작 문서화 |

---

### Task 1: Redis 스키마와 최신성 판정

**Files:**
- Create: `api/_cache.py`
- Create: `tests/test_cache.py`

**Interfaces:**
- Consumes: Redis `HGETALL`을 정규화한 `dict[str, str]`, 서버 UTC Unix 초
- Produces: `complex_key(hm, pb) -> str`, `topology_field(sn) -> str`, `unit_field(dong, ho) -> str`, `assemble_snapshot(raw, now) -> Snapshot`

- [ ] **Step 1: 키 인코딩과 스냅샷 상태의 실패 테스트를 작성한다**

```python
# tests/test_cache.py
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import _cache

NOW = 1_784_871_000
DAY = 24 * 60 * 60
WEEK = 7 * DAY


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def complete_raw(unit_status="info", unit_checked_at=NOW):
    return {
        "_dongs": encoded({"dongs": [{"sn": 1, "name": "101"}], "checked_at": NOW}),
        "t:1": encoded({
            "sn": 1,
            "hos": ["201"],
            "grid": {"cells": {"201": [2, "01"]}},
            "checked_at": NOW,
        }),
        "_supply": encoded({"supply": [], "checked_at": NOW}),
        _cache.unit_field("101", "201"): encoded({
            "dong": "101",
            "ho": "201",
            "status": unit_status,
            "fields": {},
            "checked_at": unit_checked_at,
        }),
    }


class KeySchemaTest(unittest.TestCase):
    def test_단지와_호실_식별자를_안전하게_인코딩한다(self):
        self.assertEqual(_cache.complex_key("2025000439", "2025000439"),
                         "scan:v1:2025000439:2025000439")
        self.assertEqual(_cache.unit_field("101:A", "20/1"), "u:101%3AA:20%2F1")

    def test_지나치게_긴_식별자는_거부한다(self):
        with self.assertRaises(ValueError):
            _cache.unit_field("1" * 65, "201")


class SnapshotPolicyTest(unittest.TestCase):
    def test_빈_hash는_miss다(self):
        result = _cache.assemble_snapshot({}, NOW)
        self.assertEqual(result.payload["cache"], "miss")
        self.assertTrue(result.payload["refresh"]["topology"])

    def test_완전한_당일_snapshot은_fresh다(self):
        result = _cache.assemble_snapshot(complete_raw(), NOW)
        self.assertEqual(result.payload["cache"], "fresh")
        self.assertTrue(result.payload["complete"])
        self.assertEqual(result.payload["meta"]["total"], 1)

    def test_누락_호실만_partial_refresh에_넣는다(self):
        raw = complete_raw()
        del raw[_cache.unit_field("101", "201")]
        result = _cache.assemble_snapshot(raw, NOW)
        self.assertEqual(result.payload["cache"], "partial")
        self.assertEqual(result.payload["refresh"]["units"], [{"dong": "101", "ho": "201"}])

    def test_empty는_24시간부터_재확인한다(self):
        raw = complete_raw("empty", NOW - DAY)
        result = _cache.assemble_snapshot(raw, NOW)
        self.assertEqual(result.payload["cache"], "stale")
        self.assertEqual(result.payload["refresh"]["units"], [{"dong": "101", "ho": "201"}])

    def test_최근_재확인_실패는_24시간_자동_재시도를_막는다(self):
        raw = complete_raw("info", NOW - WEEK)
        field = _cache.unit_field("101", "201")
        unit = json.loads(raw[field])
        unit["last_error_at"] = NOW
        raw[field] = encoded(unit)
        self.assertEqual(_cache.assemble_snapshot(raw, NOW).payload["refresh"]["units"], [])
        unit["last_error_at"] = NOW - DAY
        raw[field] = encoded(unit)
        self.assertEqual(_cache.assemble_snapshot(raw, NOW).payload["refresh"]["units"],
                         [{"dong": "101", "ho": "201"}])

    def test_손상된_호실_JSON은_partial로_복구한다(self):
        raw = complete_raw()
        raw[_cache.unit_field("101", "201")] = "not-json"
        result = _cache.assemble_snapshot(raw, NOW)
        self.assertEqual(result.payload["cache"], "partial")
        self.assertFalse(result.payload["complete"])

    def test_info와_topology는_7일부터_전체_재확인한다(self):
        raw = complete_raw("info", NOW - WEEK)
        raw["_dongs"] = encoded({"dongs": [{"sn": 1, "name": "101"}],
                                  "checked_at": NOW - WEEK})
        raw["t:1"] = encoded({"sn": 1, "hos": ["201"], "grid": None,
                               "checked_at": NOW - WEEK})
        result = _cache.assemble_snapshot(raw, NOW)
        self.assertTrue(result.payload["refresh"]["topology"])
        self.assertTrue(result.payload["refresh"]["all_units"])
        self.assertTrue(result.payload["refresh"]["supply"])

    def test_현재_topology에_없는_호실은_고아로_분류한다(self):
        raw = complete_raw()
        orphan = _cache.unit_field("102", "301")
        raw[orphan] = encoded({"dong": "102", "ho": "301", "status": "empty",
                               "fields": {}, "checked_at": NOW})
        result = _cache.assemble_snapshot(raw, NOW)
        self.assertEqual(result.orphan_fields, (orphan,))
```

- [ ] **Step 2: 새 테스트가 모듈 부재로 실패하는지 확인한다**

Run: `python3 -m unittest tests.test_cache -v`

Expected: `ModuleNotFoundError: No module named '_cache'`

- [ ] **Step 3: 상수, 키 함수, `Snapshot`, `assemble_snapshot`을 구현한다**

```python
# api/_cache.py
from __future__ import annotations

import json
import urllib.parse
from dataclasses import dataclass
from typing import Mapping

DAY_SECONDS = 24 * 60 * 60
TOPOLOGY_MAX_AGE = 7 * DAY_SECONDS
CACHE_TTL = 90 * DAY_SECONDS
FULL_REFRESH_COOLDOWN = 10 * 60
UNIT_LOCK_TTL = 30
REDIS_TIMEOUT = 2.0
CIRCUIT_BREAKER_SECONDS = 60.0


@dataclass(frozen=True)
class Snapshot:
    payload: dict
    orphan_fields: tuple[str, ...] = ()


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
        if not unit:
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
```

- [ ] **Step 4: 정책 테스트를 다시 실행한다**

Run: `python3 -m unittest tests.test_cache -v`

Expected: 10 tests, `OK`

- [ ] **Step 5: 첫 캐시 정책 단위를 커밋한다**

```bash
git add api/_cache.py tests/test_cache.py
git commit -m "feat: 공유 캐시 스냅샷 정책 추가"
```

---

### Task 2: Upstash REST transport와 Hash 영속화

**Files:**
- Modify: `api/_cache.py`
- Modify: `tests/test_cache.py`

**Interfaces:**
- Consumes: `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN`, Task 1의 `assemble_snapshot`
- Produces: `UpstashTransport.pipeline(commands) -> list[object]`, `CacheStore.from_env()`, `CacheStore.read_snapshot()`, `write_dongs()`, `write_hos()`, `write_supply()`, `write_unit()`

- [ ] **Step 1: REST 응답, pipeline 명령, TTL, 회로 차단 테스트를 추가한다**

```python
# tests/test_cache.py에 추가
class FakeTransport:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    def pipeline(self, commands):
        self.calls.append(commands)
        if not self.responses:
            return [None for command in commands]
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class PersistenceTest(unittest.TestCase):
    def test_hash를_읽고_TTL을_연장한다(self):
        raw = complete_raw()
        flat = [part for item in raw.items() for part in item]
        transport = FakeTransport([[flat, 1]])
        store = _cache.CacheStore(transport, now=lambda: NOW)
        payload = store.read_snapshot("2025000439", "2025000439")
        self.assertEqual(payload["cache"], "fresh")
        self.assertEqual(transport.calls[0], [
            ["HGETALL", "scan:v1:2025000439:2025000439"],
            ["EXPIRE", "scan:v1:2025000439:2025000439", _cache.CACHE_TTL],
        ])

    def test_호실_하나만_HSET하고_TTL을_연장한다(self):
        transport = FakeTransport([[1, 1]])
        store = _cache.CacheStore(transport, now=lambda: NOW)
        store.write_unit("1", "2", {"dong": "101", "ho": "201",
                                      "status": "empty", "fields": {}})
        commands = transport.calls[0]
        self.assertEqual(commands[0][:3], ["HSET", "scan:v1:1:2", "u:101:201"])
        saved = json.loads(commands[0][3])
        self.assertEqual(saved["checked_at"], NOW)
        self.assertEqual(commands[1], ["EXPIRE", "scan:v1:1:2", _cache.CACHE_TTL])

    def test_환경변수_둘_중_하나라도_없으면_비활성화한다(self):
        self.assertIsNone(_cache.CacheStore.from_env({}))
        self.assertIsNone(_cache.CacheStore.from_env({"UPSTASH_REDIS_REST_URL": "https://x"}))

    def test_전송_실패_뒤_60초_동안_회로를_차단한다(self):
        calls = []
        clock = iter([10.0, 10.0, 20.0, 71.0, 71.0])

        def request(url, token, commands, timeout):
            calls.append((url, token, commands, timeout))
            if len(calls) == 1:
                raise OSError("offline")
            return ["OK"]

        transport = _cache.UpstashTransport("https://redis.example", "secret",
                                             request=request, monotonic=lambda: next(clock))
        with self.assertRaises(_cache.CacheUnavailable):
            transport.pipeline([["PING"]])
        with self.assertRaises(_cache.CacheUnavailable):
            transport.pipeline([["PING"]])
        self.assertEqual(transport.pipeline([["PING"]]), ["OK"])
        self.assertEqual(len(calls), 2)
```

- [ ] **Step 2: 새 persistence 테스트가 클래스 부재로 실패하는지 확인한다**

Run: `python3 -m unittest tests.test_cache.PersistenceTest -v`

Expected: FAIL with `AttributeError` for `CacheStore` or `UpstashTransport`

- [ ] **Step 3: REST transport와 CacheStore 읽기·쓰기를 구현한다**

```python
# api/_cache.py import에 추가
import os
import time
import urllib.request
import uuid
from collections.abc import Callable, Sequence


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
```

- [ ] **Step 4: transport와 기존 정책 테스트를 실행한다**

Run: `python3 -m unittest tests.test_cache -v`

Expected: 14 tests, `OK`

- [ ] **Step 5: transport 단위를 커밋한다**

```bash
git add api/_cache.py tests/test_cache.py
git commit -m "feat: Upstash REST 캐시 영속화 추가"
```

---

### Task 3: 호실 잠금, 전체 cooldown, 오류 시 정상값 보존

**Files:**
- Modify: `api/_cache.py`
- Modify: `tests/test_cache.py`

**Interfaces:**
- Consumes: Task 2의 `CacheStore`, Redis `SET NX EX`, `HGET`, `TTL`, `EVAL`
- Produces: `LockResult`, `claim_unit()`, `release_unit()`, `read_unit()`, `claim_full_refresh()`, `record_unit_error()`

- [ ] **Step 1: 잠금 경합과 오류 보존 실패 테스트를 추가한다**

```python
# tests/test_cache.py에 추가
class CoordinationTest(unittest.TestCase):
    def test_호실_잠금을_30초로_획득한다(self):
        transport = FakeTransport([["OK"]])
        store = _cache.CacheStore(transport, now=lambda: NOW)
        result = store.claim_unit("1", "2", "101", "201", token="owner")
        self.assertEqual(result.state, "acquired")
        self.assertEqual(result.token, "owner")
        self.assertEqual(transport.calls[0][0][-4:], ["owner", "NX", "EX", 30])

    def test_이미_잠긴_호실은_busy다(self):
        store = _cache.CacheStore(FakeTransport([[None]]), now=lambda: NOW)
        result = store.claim_unit("1", "2", "101", "201", token="other")
        self.assertEqual(result.state, "busy")

    def test_소유자_토큰을_비교해_잠금을_해제한다(self):
        transport = FakeTransport([[1]])
        store = _cache.CacheStore(transport, now=lambda: NOW)
        self.assertTrue(store.release_unit("1", "2", "101", "201", "owner"))
        command = transport.calls[0][0]
        self.assertEqual(command[0], "EVAL")
        self.assertEqual(command[-1], "owner")

    def test_전체_새로고침_cooldown의_남은_초를_돌려준다(self):
        transport = FakeTransport([[None, 412]])
        store = _cache.CacheStore(transport, now=lambda: NOW)
        self.assertEqual(store.claim_full_refresh("1", "2"),
                         {"allowed": False, "retry_after": 412})

    def test_정상값_재확인_실패는_상태를_보존한다(self):
        old = {"dong": "101", "ho": "201", "status": "info",
               "fields": {"주택형": "084.8422A"}, "checked_at": NOW - WEEK}
        transport = FakeTransport([[
            json.dumps(old, ensure_ascii=False)
        ], [1, 1]])
        store = _cache.CacheStore(transport, now=lambda: NOW)
        saved = store.record_unit_error("1", "2", "101", "201", "타임아웃")
        self.assertEqual(saved["status"], "info")
        self.assertEqual(saved["last_error_at"], NOW)
        self.assertNotIn("타임아웃", json.dumps(transport.calls))

    def test_첫_조회_실패는_error로_저장한다(self):
        transport = FakeTransport([[None], [1, 1]])
        store = _cache.CacheStore(transport, now=lambda: NOW)
        saved = store.record_unit_error("1", "2", "101", "201", "타임아웃")
        self.assertEqual(saved["status"], "error")
        self.assertEqual(saved["fields"], {})
```

- [ ] **Step 2: coordination 테스트가 메서드 부재로 실패하는지 확인한다**

Run: `python3 -m unittest tests.test_cache.CoordinationTest -v`

Expected: FAIL with `AttributeError` for `claim_unit`

- [ ] **Step 3: 잠금·cooldown·오류 보존 메서드를 구현한다**

```python
# api/_cache.py에 추가
@dataclass(frozen=True)
class LockResult:
    state: str
    token: str | None = None


_RELEASE_SCRIPT = (
    'if redis.call("get", KEYS[1]) == ARGV[1] then '
    'return redis.call("del", KEYS[1]) else return 0 end'
)


def _unit_lock_key(hm, pb, dong, ho):
    return f"lock:{complex_key(hm, pb)}:{_part(dong)}:{_part(ho)}"


def _full_refresh_key(hm, pb):
    return f"cooldown:{complex_key(hm, pb)}:full"


# 다음 메서드를 CacheStore 클래스 본문에 추가한다.
    def claim_unit(self, hm, pb, dong, ho, token=None):
        owner = token or uuid.uuid4().hex
        try:
            result = self.transport.pipeline([
                ["SET", _unit_lock_key(hm, pb, dong, ho), owner,
                 "NX", "EX", UNIT_LOCK_TTL]
            ])[0]
        except (CacheUnavailable, ValueError):
            return LockResult("unavailable")
        return LockResult("acquired", owner) if result == "OK" else LockResult("busy")

    def release_unit(self, hm, pb, dong, ho, token):
        try:
            result = self.transport.pipeline([[
                "EVAL", _RELEASE_SCRIPT, 1,
                _unit_lock_key(hm, pb, dong, ho), token
            ]])[0]
            return bool(result)
        except (CacheUnavailable, ValueError):
            return False

    def claim_full_refresh(self, hm, pb):
        key = _full_refresh_key(hm, pb)
        token = uuid.uuid4().hex
        try:
            result, ttl = self.transport.pipeline([
                ["SET", key, token, "NX", "EX", FULL_REFRESH_COOLDOWN],
                ["TTL", key],
            ])
            return {"allowed": result == "OK",
                    "retry_after": 0 if result == "OK" else max(int(ttl or 0), 0)}
        except (CacheUnavailable, ValueError):
            return {"allowed": True, "retry_after": 0}

    def read_unit(self, hm, pb, dong, ho):
        try:
            result = self.transport.pipeline([[
                "HGET", complex_key(hm, pb), unit_field(dong, ho)
            ]])[0]
            return json.loads(result) if result else None
        except (CacheUnavailable, ValueError, json.JSONDecodeError):
            return None

    def record_unit_error(self, hm, pb, dong, ho, message):
        prior = self.read_unit(hm, pb, dong, ho)
        if prior and prior.get("status") in {"info", "empty"}:
            saved = dict(prior)
            saved["last_error_at"] = self.now()
            saved["last_error"] = "최근 갱신에 실패했습니다."
            self._write(hm, pb, unit_field(dong, ho), saved)
            return saved
        saved = {"dong": dong, "ho": ho, "status": "error", "fields": {}}
        self._write(hm, pb, unit_field(dong, ho), saved)
        saved["checked_at"] = self.now()
        return saved
```

`record_unit_error`에는 원본 예외 문자열을 저장하지 않고 고정 문구만 저장해 내부 URL이나 민감한
오류가 공유 데이터로 남지 않게 한다.

- [ ] **Step 4: 전체 cache 테스트를 실행한다**

Run: `python3 -m unittest tests.test_cache -v`

Expected: 20 tests, `OK`

- [ ] **Step 5: coordination 단위를 커밋한다**

```bash
git add api/_cache.py tests/test_cache.py
git commit -m "feat: 공유 캐시 갱신 잠금 추가"
```

---

### Task 4: `/api/cache`와 기존 API write-through

**Files:**
- Create: `api/cache.py`
- Modify: `api/_lib.py:13-134`
- Modify: `tests/test_api.py:9-190`
- Modify: `tests/test_server_search.py:65-70`

**Interfaces:**
- Consumes: Task 2·3의 `CacheStore`
- Produces: `_lib.cache_snapshot(query) -> tuple[int, dict]`, `GET /api/cache`, 기존 API의 서버 검증 write-through, `/api/unit`의 `200 refreshing` 또는 `202 refreshing`

- [ ] **Step 1: cache route와 write-through 실패 테스트를 추가한다**

```python
# tests/test_api.py import에 추가
import _cache


class FakeCache:
    def __init__(self):
        self.calls = []
        self.snapshot = {"cache": "fresh", "complete": True, "checked_at": NOW,
                         "meta": {"total": 0, "dongs": [], "supply": []},
                         "units": [],
                         "refresh": {"topology": False, "supply": False,
                                     "all_units": False, "units": []}}
        self.lock = _cache.LockResult("acquired", "owner")
        self.cached_unit = None

    def read_snapshot(self, hm, pb, request_full=False):
        self.calls.append(("read_snapshot", hm, pb, request_full))
        return dict(self.snapshot)

    def write_dongs(self, hm, pb, dongs):
        self.calls.append(("write_dongs", hm, pb, dongs))

    def write_hos(self, hm, pb, sn, hos, grid):
        self.calls.append(("write_hos", hm, pb, sn, hos, grid))

    def write_supply(self, hm, pb, supply):
        self.calls.append(("write_supply", hm, pb, supply))

    def write_unit(self, hm, pb, unit):
        self.calls.append(("write_unit", hm, pb, unit))

    def claim_unit(self, hm, pb, dong, ho):
        return self.lock

    def release_unit(self, hm, pb, dong, ho, token):
        self.calls.append(("release_unit", token))

    def read_unit(self, hm, pb, dong, ho):
        return self.cached_unit

    def record_unit_error(self, hm, pb, dong, ho, message):
        self.calls.append(("record_unit_error", dong, ho))
        return {"dong": dong, "ho": ho, "status": "error", "fields": {}}

    def claim_full_refresh(self, hm, pb):
        self.calls.append(("claim_full_refresh", hm, pb))
        return {"allowed": True, "retry_after": 0}


class CacheIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.original_cache = _lib.CACHE
        self.cache = FakeCache()
        _lib.CACHE = self.cache

    def tearDown(self):
        _lib.CACHE = self.original_cache

    def test_cache_route가_snapshot을_반환한다(self):
        status, body = _lib.cache_snapshot(q(hm="1", pb="2"))
        self.assertEqual(status, 200)
        self.assertEqual(body["cache"], "fresh")

    def test_수동_전체_새로고침이_cooldown을_획득한다(self):
        status, body = _lib.cache_snapshot(q(hm="1", pb="2", refresh="full"))
        self.assertEqual(status, 200)
        self.assertTrue(body["full_refresh"]["allowed"])
        self.assertIn(("claim_full_refresh", "1", "2"), self.cache.calls)

    def test_cache가_없으면_disabled로_직접_조회를_지시한다(self):
        _lib.CACHE = None
        try:
            status, body = _lib.cache_snapshot(q(hm="1", pb="2"))
        finally:
            _lib.CACHE = self.cache
        self.assertEqual(status, 200)
        self.assertEqual(body["cache"], "disabled")
        self.assertTrue(body["refresh"]["all_units"])

    def test_dongs가_서버에서_받은_값을_write_through한다(self):
        original = applyhome.list_dongs
        applyhome.list_dongs = lambda hm, pb: [applyhome.Dong(1, "101")]
        try:
            _lib.dongs(q(hm="1", pb="2"))
        finally:
            applyhome.list_dongs = original
        self.assertIn(("write_dongs", "1", "2", [{"sn": 1, "name": "101"}]),
                      self.cache.calls)

    def test_cache_write_실패가_원본_API를_실패시키지_않는다(self):
        original = applyhome.list_dongs
        applyhome.list_dongs = lambda hm, pb: [applyhome.Dong(1, "101")]

        def broken_write(hm, pb, dongs):
            raise RuntimeError("redis offline")

        self.cache.write_dongs = broken_write
        try:
            status, body = _lib.dongs(q(hm="1", pb="2"))
        finally:
            applyhome.list_dongs = original
        self.assertEqual(status, 200)
        self.assertEqual(body["dongs"], [{"sn": 1, "name": "101"}])

    def test_unit_잠금_경합과_기존값은_200_refreshing이다(self):
        self.cache.lock = _cache.LockResult("busy")
        self.cache.cached_unit = {"dong": "101", "ho": "201", "status": "empty",
                                  "fields": {}, "checked_at": NOW - DAY}
        status, body = _lib.unit(q(hm="1", pb="2", dong="101", ho="201"))
        self.assertEqual(status, 200)
        self.assertTrue(body["refreshing"])

    def test_unit_잠금_경합과_기존값_없음은_202다(self):
        self.cache.lock = _cache.LockResult("busy")
        status, body = _lib.unit(q(hm="1", pb="2", dong="101", ho="201"))
        self.assertEqual(status, 202)
        self.assertEqual(body["status"], "refreshing")

    def test_unit_성공은_저장하고_소유자_잠금을_해제한다(self):
        original = applyhome.fetch_detail
        applyhome.fetch_detail = lambda hm, pb, dong, ho: applyhome.UnitDetail(
            dong, ho, "info", {"주택형": "084.8422A"})
        try:
            status, body = _lib.unit(q(hm="1", pb="2", dong="101", ho="201"))
        finally:
            applyhome.fetch_detail = original
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "info")
        self.assertTrue(any(call[0] == "write_unit" for call in self.cache.calls))
        self.assertIn(("release_unit", "owner"), self.cache.calls)
```

`tests/test_api.py` 상단에 `NOW = 1_784_871_000`, `DAY = 86_400`도 추가한다.

- [ ] **Step 2: 새 API 테스트가 `CACHE`와 route 부재로 실패하는지 확인한다**

Run: `python3 -m unittest tests.test_api.CacheIntegrationTest -v`

Expected: FAIL with `AttributeError: module '_lib' has no attribute 'CACHE'`

- [ ] **Step 3: `_lib`에 cache 초기화, 안전 호출, route를 구현한다**

```python
# api/_lib.py import와 전역에 추가
import _cache

CACHE = _cache.CacheStore.from_env()


def _cache_call(method: str, *args):
    if CACHE is None:
        return None
    try:
        return getattr(CACHE, method)(*args)
    except Exception:
        return None


def cache_snapshot(query: dict) -> tuple[int, dict]:
    hm, pb = one(query, "hm"), one(query, "pb")
    if not (hm and pb):
        return 400, {"message": "hm, pb 값이 필요합니다."}
    request_full = one(query, "refresh") == "full"
    if CACHE is None:
        return 200, {
            "cache": "disabled", "complete": False, "checked_at": None,
            "meta": None, "units": [],
            "refresh": {"topology": True, "supply": True,
                        "all_units": True, "units": []},
            "full_refresh": {"allowed": True, "retry_after": 0},
        }
    body = CACHE.read_snapshot(hm, pb, request_full=request_full)
    if request_full or (body["cache"] == "stale" and body["refresh"]["all_units"]):
        body["full_refresh"] = (_cache_call("claim_full_refresh", hm, pb) or
                                {"allowed": True, "retry_after": 0})
    return 200, body
```

기존 함수의 성공 return 직전에 다음 호출을 넣는다.

```python
# dongs
payload = {"dongs": [{"sn": d.sn, "name": d.name} for d in found]}
_cache_call("write_dongs", hm, pb, payload["dongs"])
return 200, payload

# hos
payload = {"hos": numbers, "grid": grid.build_grid(numbers)}
_cache_call("write_hos", hm, pb, sn, payload["hos"], payload["grid"])
return 200, payload
```

`pblanc`는 다음 전체 본문으로 바꿔 `None`도 24시간 재확인 가능한 값으로 저장한다.

```python
def pblanc(query: dict) -> tuple[int, dict]:
    hm, pb = one(query, "hm"), one(query, "pb")
    if not (hm and pb):
        return 400, {"message": "hm, pb 값이 필요합니다."}
    try:
        types = applyhome.fetch_pblanc_supply(hm, pb)
    except Exception:
        types = []
    supply = [
        {
            "type": item.house_type,
            "short": grid.short_type(item.house_type),
            "net_area": grid.net_area(item.house_type),
            "area": item.area,
            "general": item.general,
            "special": item.special,
            "total": item.total,
        }
        for item in types
    ] or None
    payload = {"supply": supply}
    _cache_call("write_supply", hm, pb, supply)
    return 200, payload
```

`dongs`·`hos`의 502 경로에는 write-through를 넣지 않는다.

- [ ] **Step 4: `/api/unit`에 잠금, 오류 보존, release를 구현한다**

```python
# api/_lib.py의 unit 함수에서 applyhome.fetch_detail 호출을 이 구조로 교체
lock = _cache_call("claim_unit", hm, pb, dong, ho)
if lock is not None and lock.state == "busy":
    cached = _cache_call("read_unit", hm, pb, dong, ho)
    if cached:
        return 200, {**cached, "refreshing": True, "source": "cache"}
    return 202, {"dong": dong, "ho": ho, "status": "refreshing",
                 "fields": {}, "refreshing": True}

token = lock.token if lock is not None and lock.state == "acquired" else None
try:
    try:
        found = applyhome.fetch_detail(hm, pb, dong, ho)
    except applyhome.ApplyhomeError as error:
        saved = _cache_call("record_unit_error", hm, pb, dong, ho, str(error))
        if saved:
            return 200, {**saved, "refresh_error": True}
        return 200, {"dong": dong, "ho": ho, "status": "error", "fields": {},
                     "message": str(error)}
    payload = {"dong": found.dong, "ho": found.ho,
               "status": found.status, "fields": found.fields}
    _cache_call("write_unit", hm, pb, payload)
    return 200, payload
finally:
    if token:
        _cache_call("release_unit", hm, pb, dong, ho, token)
```

- [ ] **Step 5: Vercel entrypoint와 route 등록을 추가한다**

```python
# api/cache.py
"""Vercel 캐시 조회 진입점. 로직은 _lib 에 있다."""

import pathlib
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import _lib


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _lib.respond(self, *_lib.cache_snapshot(query))
```

`_lib.ROUTES`에 `"/api/cache": cache_snapshot`을 추가하고 두 route 테스트의 기대 집합을 다음으로 바꾼다.

```python
{"/api/search", "/api/dongs", "/api/hos", "/api/unit", "/api/pblanc", "/api/cache"}
```

두 테스트 메서드 이름의 `다섯`도 `여섯`으로 바꾼다.

`tests/test_server_search.py`의 `setUpClass`와 `tearDownClass`는 로컬 환경변수에 영향받지 않도록
`_lib.CACHE`도 저장·복원한다.

```python
# setUpClass에 추가
import _lib
cls.original_cache = _lib.CACHE
_lib.CACHE = None

# tearDownClass에 추가
import _lib
_lib.CACHE = cls.original_cache

# RoutingTest에 추가
def test_cache_미설정은_disabled_JSON이다(self):
    status, raw = self.get("/api/cache?hm=1&pb=2")
    self.assertEqual(status, 200)
    self.assertEqual(json.loads(raw)["cache"], "disabled")
```

- [ ] **Step 6: API와 전체 Python 테스트를 실행한다**

Run: `python3 -m unittest tests.test_api tests.test_cache tests.test_server_search -v`

Expected: all tests `OK`

- [ ] **Step 7: API 통합 단위를 커밋한다**

```bash
git add api/_cache.py api/_lib.py api/cache.py tests/test_api.py tests/test_server_search.py
git commit -m "feat: 공유 캐시 API와 write-through 연결"
```

---

### Task 5: 테스트 가능한 프런트엔드 캐시 헬퍼

**Files:**
- Create: `public/cache.mjs`
- Create: `tests/test_frontend_cache.mjs`
- Modify: `server.py:28-42`
- Modify: `tests/test_server_search.py:55-70`

**Interfaces:**
- Consumes: `/api/cache` JSON과 현재 topology 작업 목록
- Produces: `unitKey`, `hydrateState`, `mergeUnits`, `selectUnitJobs`, `pollSharedSnapshot`, `formatCheckedAt`

- [ ] **Step 1: 프런트엔드 상태 병합과 작업 선택 실패 테스트를 작성한다**

```javascript
// tests/test_frontend_cache.mjs
import test from "node:test";
import assert from "node:assert/strict";
import {
  POLL_DELAYS_MS, formatCheckedAt, hydrateState, mergeUnits,
  pollSharedSnapshot, selectUnitJobs, unitKey,
} from "../public/cache.mjs";

const snapshot = {
  cache: "partial",
  checked_at: 1784871000,
  meta: { total: 2, dongs: [{ name: "101", hos: ["201", "202"], grid: null }], supply: [] },
  units: [{ dong: "101", ho: "201", status: "info", fields: {}, checked_at: 1784871000 }],
  refresh: { topology: false, supply: false, all_units: false,
             units: [{ dong: "101", ho: "202" }] },
};

test("snapshot을 기존 state 형태로 옮긴다", () => {
  const state = { meta: null, units: new Map() };
  hydrateState(state, snapshot);
  assert.equal(state.meta.total, 2);
  assert.equal(state.units.get("101\u0000201").status, "info");
});

test("partial은 저장되지 않은 호실만 선택한다", () => {
  const jobs = [{ dong: "101", ho: "201" }, { dong: "101", ho: "202" }];
  assert.deepEqual(selectUnitJobs(snapshot, jobs), [{ dong: "101", ho: "202" }]);
});

test("all_units는 현재 topology 전체를 선택한다", () => {
  const body = structuredClone(snapshot);
  body.cache = "stale";
  body.refresh.all_units = true;
  const jobs = [{ dong: "101", ho: "201" }, { dong: "101", ho: "202" }];
  assert.deepEqual(selectUnitJobs(body, jobs), jobs);
});

test("공유 결과는 0.5, 1, 2초 순서로 polling한다", async () => {
  const waits = [];
  const bodies = [{ checked_at: 1 }, { checked_at: 2 }];
  const found = await pollSharedSnapshot(
    async () => bodies.shift(),
    (body) => body.checked_at === 2,
    async (delay) => waits.push(delay),
  );
  assert.equal(found.checked_at, 2);
  assert.deepEqual(waits, POLL_DELAYS_MS.slice(0, 2));
});

test("checked_at이 없으면 표시 문자열이 비어 있다", () => {
  assert.equal(formatCheckedAt(null), "");
  assert.equal(unitKey("101", "201"), "101\u0000201");
});
```

- [ ] **Step 2: Node 테스트가 모듈 부재로 실패하는지 확인한다**

Run: `node --test tests/test_frontend_cache.mjs`

Expected: FAIL with `ERR_MODULE_NOT_FOUND`

- [ ] **Step 3: 순수 캐시 헬퍼 모듈을 구현한다**

```javascript
// public/cache.mjs
export const POLL_DELAYS_MS = [500, 1000, 2000];

export function unitKey(dong, ho) {
  return `${dong}\u0000${ho}`;
}

export function mergeUnits(target, units) {
  for (const unit of units || []) target.set(unitKey(unit.dong, unit.ho), unit);
  return target;
}

export function hydrateState(state, snapshot) {
  state.meta = snapshot.meta;
  state.units = mergeUnits(new Map(), snapshot.units);
  state.cache = { status: snapshot.cache, checkedAt: snapshot.checked_at };
  return state;
}

export function selectUnitJobs(snapshot, jobs) {
  if (!snapshot || snapshot.cache === "disabled" || snapshot.cache === "miss") return jobs.slice();
  if (snapshot.refresh?.all_units) return jobs.slice();
  const requested = new Set((snapshot.refresh?.units || [])
    .map((unit) => unitKey(unit.dong, unit.ho)));
  if (snapshot.cache === "partial") {
    const saved = new Set((snapshot.units || []).map((unit) => unitKey(unit.dong, unit.ho)));
    return jobs.filter((job) => !saved.has(unitKey(job.dong, job.ho)) ||
      requested.has(unitKey(job.dong, job.ho)));
  }
  return jobs.filter((job) => requested.has(unitKey(job.dong, job.ho)));
}

export async function pollSharedSnapshot(load, accept, wait =
  (delay) => new Promise((resolve) => setTimeout(resolve, delay))) {
  for (const delay of POLL_DELAYS_MS) {
    await wait(delay);
    const snapshot = await load();
    if (accept(snapshot)) return snapshot;
  }
  return null;
}

export function formatCheckedAt(value) {
  if (!value) return "";
  return new Date(value * 1000).toLocaleString("ko-KR", {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false,
  });
}
```

- [ ] **Step 4: 로컬 서버가 ES module을 올바른 MIME으로 서빙하게 한다**

```python
# server.py do_GET에서 API route 탐색 전에 추가
if parsed.path == "/cache.mjs":
    self._send_file(PUBLIC_DIR / "cache.mjs", "text/javascript; charset=utf-8")
    return
```

```python
# tests/test_server_search.py에 추가
def test_cache_module을_javascript로_준다(self):
    url = f"http://127.0.0.1:{self.port}/cache.mjs"
    with urllib.request.urlopen(url, timeout=5) as response:
        self.assertEqual(response.headers.get_content_type(), "text/javascript")
        self.assertIn("selectUnitJobs", response.read().decode("utf-8"))
```

- [ ] **Step 5: Node와 로컬 server 테스트를 실행한다**

Run: `node --test tests/test_frontend_cache.mjs`

Expected: 5 tests, 5 pass

Run: `python3 -m unittest tests.test_server_search -v`

Expected: all tests `OK`

- [ ] **Step 6: 프런트엔드 헬퍼 단위를 커밋한다**

```bash
git add public/cache.mjs server.py tests/test_frontend_cache.mjs tests/test_server_search.py
git commit -m "feat: 프런트엔드 캐시 작업 헬퍼 추가"
```

---

### Task 6: 캐시 우선 렌더링과 부분 갱신

**Files:**
- Modify: `public/index.html:135-439`
- Modify: `tests/test_frontend_cache.mjs`

**Interfaces:**
- Consumes: Task 4의 `/api/cache`, Task 5의 `hydrateState`, `selectUnitJobs`, 기존 `/api/dongs`, `/api/hos`, `/api/pblanc`, `/api/unit`
- Produces: `scanComplex({forceFull})`, 저장 결과 즉시 렌더링, missing·24시간·7일 작업만 실행하는 대기열

- [ ] **Step 1: refresh 작업 선택의 fresh·stale 경계 테스트를 추가한다**

```javascript
// tests/test_frontend_cache.mjs에 추가
test("fresh는 호실 요청을 만들지 않는다", () => {
  const body = structuredClone(snapshot);
  body.cache = "fresh";
  body.refresh.units = [];
  const jobs = [{ dong: "101", ho: "201" }, { dong: "101", ho: "202" }];
  assert.deepEqual(selectUnitJobs(body, jobs), []);
});

test("stale은 서버가 지정한 호실만 선택한다", () => {
  const body = structuredClone(snapshot);
  body.cache = "stale";
  body.refresh.units = [{ dong: "101", ho: "201" }];
  const jobs = [{ dong: "101", ho: "201" }, { dong: "101", ho: "202" }];
  assert.deepEqual(selectUnitJobs(body, jobs), [{ dong: "101", ho: "201" }]);
});
```

- [ ] **Step 2: 선택 테스트를 실행해 현재 helper가 경계를 지키는지 확인한다**

Run: `node --test tests/test_frontend_cache.mjs`

Expected: 7 tests, 7 pass

- [ ] **Step 3: HTML script를 ES module로 바꾸고 cache state를 추가한다**

```html
<!-- public/index.html -->
<script type="module">
import {
  formatCheckedAt, hydrateState, mergeUnits, pollSharedSnapshot,
  selectUnitJobs, unitKey,
} from "/cache.mjs";
```

```javascript
const state = {
  complex: null, meta: null, units: new Map(), aborted: false,
  cache: { status: "disabled", checkedAt: null },
  search: { name: "", area: "", page: 1, loaded: 0, total: 0 },
};
```

기존 `dong + "-" + ho` 형태로 Map을 읽고 쓰는 모든 표현을 `unitKey(dong, ho)`로 바꾼다.
대상은 신규 호실 저장, 재시도 저장, 상세 보기이며 캐시 스냅샷 병합도 같은 함수를 사용한다.

- [ ] **Step 4: 기존 click handler를 캐시 우선 `scanComplex`로 교체한다**

```javascript
async function fetchTopology(hm, pb) {
  const { dongs } = await getJson("/api/dongs", { hm, pb });
  if (!dongs.length) return { total: 0, dongs: [], supply: null };
  const perDong = await runPool(dongs, (dong) =>
    getJson("/api/hos", { hm, pb, sn: dong.sn })
      .then((result) => ({ ...result, name: dong.name }))
  );
  const metaDongs = perDong.filter(Boolean).map((dong) => ({
    name: dong.name, hos: dong.hos, grid: dong.grid,
  }));
  return {
    total: metaDongs.reduce((sum, dong) => sum + dong.hos.length, 0),
    dongs: metaDongs,
    supply: null,
  };
}

function jobsFromMeta(meta) {
  const jobs = [];
  for (const dong of meta?.dongs || []) {
    for (const ho of dong.hos) jobs.push({ dong: dong.name, ho });
  }
  return jobs;
}

function summarize(elapsed = "0.0") {
  const tally = { info: 0, empty: 0, error: 0 };
  state.units.forEach((unit) => {
    tally[unit.status] = (tally[unit.status] || 0) + 1;
  });
  return { total: state.meta?.total || 0, ...tally, elapsed };
}

function renderStoredSnapshot(snapshot) {
  if (!snapshot.meta) return;
  hydrateState(state, snapshot);
  onMeta(state.meta);
  state.units.forEach(onUnit);
  onDone(summarize());
  const checked = formatCheckedAt(snapshot.checked_at);
  el("progress").textContent = checked
    ? `저장된 결과 ${state.units.size} / ${state.meta.total} · 마지막 확인 ${checked}`
    : `저장된 결과 ${state.units.size} / ${state.meta.total}`;
}

async function scanComplex({ forceFull = false } = {}) {
  if (!state.complex) return;
  state.meta = null;
  state.units = new Map();
  state.aborted = false;
  el("grids").innerHTML = "";
  el("summary").innerHTML = "";
  el("empty-list").innerHTML = "";
  el("detail").innerHTML = "";
  el("notice-band").classList.add("hide");
  el("scan-button").disabled = true;
  el("stop-button").classList.remove("hide");

  const hm = state.complex.house_manage_no;
  const pb = state.complex.pblanc_no;
  const started = Date.now();
  let snapshot;
  try {
    snapshot = await getJson("/api/cache", {
      hm, pb, ...(forceFull ? { refresh: "full" } : {}),
    });
  } catch (error) {
    snapshot = {
      cache: "disabled", complete: false, checked_at: null, meta: null, units: [],
      refresh: { topology: true, supply: true, all_units: true, units: [] },
      full_refresh: { allowed: true, retry_after: 0 },
    };
  }

  renderStoredSnapshot(snapshot);
  if (snapshot.full_refresh && !snapshot.full_refresh.allowed) {
    el("progress").textContent =
      `다른 방문자가 업데이트 중입니다 · ${snapshot.full_refresh.retry_after}초 뒤 전체 새로고침 가능`;
    finishScan();
    return;
  }
  if (snapshot.cache === "fresh" && !forceFull) {
    finishScan();
    return;
  }

  try {
    const cachedSupply = state.meta?.supply ?? null;
    if (!state.meta || snapshot.refresh.topology || forceFull) {
      state.meta = await fetchTopology(hm, pb);
      state.meta.supply = cachedSupply;
    }
    if (!state.meta.total) {
      el("progress").textContent = "이 단지는 아직 분양권 정보가 등록되지 않았습니다.";
      finishScan();
      return;
    }
    if (snapshot.refresh.supply || forceFull || state.meta.supply === null) {
      state.meta.supply = await getJson("/api/pblanc", { hm, pb })
        .then((body) => body.supply).catch(() => null);
    }
    onMeta(state.meta);
    state.units.forEach(onUnit);

    const allJobs = jobsFromMeta(state.meta);
    const jobs = forceFull ? allJobs : selectUnitJobs(snapshot, allJobs);
    let updated = 0;
    await runPool(jobs, async (job) => {
      const unit = await getJson("/api/unit", { hm, pb, dong: job.dong, ho: job.ho })
        .catch(() => ({ dong: job.dong, ho: job.ho, status: "error", fields: {} }));
      if (unit.status !== "refreshing") {
        state.units.set(unitKey(unit.dong, unit.ho), unit);
        onUnit(unit);
      }
      updated += 1;
      el("progress").textContent =
        `저장된 결과 ${state.units.size} / ${state.meta.total} · 업데이트 ${updated} / ${jobs.length}`;
      return unit;
    });

    if (state.aborted) {
      el("progress").textContent = `중단됨 · ${state.units.size}세대까지 저장`;
      finishScan();
      return;
    }
    const summary = summarize(((Date.now() - started) / 1000).toFixed(1));
    el("progress").textContent =
      `완료 · ${summary.total}세대 중 정보없음 ${summary.empty}건` +
      (summary.error ? ` · 실패 ${summary.error}건` : "") +
      ` (${summary.elapsed}초)`;
    onDone(summary);
  } catch (error) {
    el("progress").textContent = error.message;
  } finally {
    finishScan();
  }
}

el("scan-button").addEventListener("click", () => scanComplex());
```

- [ ] **Step 5: JavaScript syntax와 helper 테스트를 실행한다**

Run: `node --check public/cache.mjs`

Expected: no output, exit 0

Run: `node --test tests/test_frontend_cache.mjs`

Expected: 7 tests, 7 pass

- [ ] **Step 6: 캐시 우선 조회 단위를 커밋한다**

```bash
git add public/index.html public/cache.mjs tests/test_frontend_cache.mjs
git commit -m "feat: 저장된 스캔 결과를 먼저 표시"
```

---

### Task 7: 동시 갱신 polling, 상태 표시, 전체 새로고침

**Files:**
- Modify: `public/index.html:25-205,326-439,688-737`
- Modify: `tests/test_frontend_cache.mjs`

**Interfaces:**
- Consumes: `/api/unit`의 `refreshing`, `/api/cache.full_refresh`, Task 5의 `pollSharedSnapshot`
- Produces: 호실 잠금 비소유자의 공유 결과 수신, cache 상태 문구, `전체 새로고침` 버튼

- [ ] **Step 1: polling 실패와 병합 테스트를 추가한다**

```javascript
// tests/test_frontend_cache.mjs에 추가
test("polling이 끝까지 최신값을 못 찾으면 null이다", async () => {
  const waits = [];
  const found = await pollSharedSnapshot(
    async () => ({ checked_at: 1 }),
    () => false,
    async (delay) => waits.push(delay),
  );
  assert.equal(found, null);
  assert.deepEqual(waits, POLL_DELAYS_MS);
});

test("새 snapshot 호실이 기존 Map 값을 교체한다", () => {
  const units = new Map([[unitKey("101", "201"), { status: "empty" }]]);
  mergeUnits(units, [{ dong: "101", ho: "201", status: "info", fields: {} }]);
  assert.equal(units.get(unitKey("101", "201")).status, "info");
});
```

- [ ] **Step 2: helper 테스트를 실행한다**

Run: `node --test tests/test_frontend_cache.mjs`

Expected: 9 tests, 9 pass

- [ ] **Step 3: `getJson`이 202 본문을 정상 반환하게 확장한다**

```javascript
async function getJson(path, params) {
  const response = await fetch(path + "?" + new URLSearchParams(params));
  const body = await response.json().catch(() => ({}));
  if (!response.ok && response.status !== 202) {
    throw new Error(body.message || `요청 실패 (${response.status})`);
  }
  return { ...body, http_status: response.status };
}
```

- [ ] **Step 4: 잠금 경합 시 `/api/cache`를 세 번 읽는 함수를 추가한다**

```javascript
async function resolveRefreshingUnit(hm, pb, job, previousCheckedAt = 0) {
  const found = await pollSharedSnapshot(
    () => getJson("/api/cache", { hm, pb }),
    (snapshot) => {
      const unit = (snapshot.units || []).find((item) =>
        item.dong === job.dong && item.ho === job.ho);
      return Boolean(unit && (unit.checked_at || 0) > previousCheckedAt);
    },
  );
  if (!found) return null;
  const unit = found.units.find((item) => item.dong === job.dong && item.ho === job.ho);
  mergeUnits(state.units, [unit]);
  onUnit(unit);
  return unit;
}
```

Task 6의 호실 worker에서 `unit.refreshing` 또는 `unit.status === "refreshing"`이면 기존 호실의
`checked_at`을 넘겨 `resolveRefreshingUnit`을 호출한다. 반환값도 없고 기존값도 없을 때만
`{dong, ho, status: "error", fields: {}}`를 화면 Map에 넣으며 이 값은 API로 보내지 않는다.

- [ ] **Step 5: 기존 실패 재시도도 202와 공유 결과를 처리하게 바꾼다**

```javascript
// renderRetry의 for loop 안 fetch 구간을 교체
const previous = state.units.get(unitKey(unit.dong, unit.ho));
let fresh = await getJson("/api/unit", {
  hm: state.complex.house_manage_no,
  pb: state.complex.pblanc_no,
  dong: unit.dong,
  ho: unit.ho,
});
if (fresh.refreshing || fresh.status === "refreshing") {
  fresh = await resolveRefreshingUnit(
    state.complex.house_manage_no,
    state.complex.pblanc_no,
    unit,
    previous?.checked_at || 0,
  );
}
if (!fresh) continue;
state.units.set(unitKey(fresh.dong, fresh.ho), fresh);
const cell = document.getElementById(cellId(fresh.dong, fresh.ho));
if (cell) {
  cell.classList.remove("error", "info", "empty");
  cell.classList.add(fresh.status);
}
```

- [ ] **Step 6: cache 상태 영역과 전체 새로고침 버튼을 추가한다**

```html
<!-- progress 옆 -->
<span id="cache-status" class="caption"></span>
```

```javascript
function renderCacheStatus(snapshot) {
  const labels = {
    disabled: "공유 캐시 없이 직접 조회",
    miss: "저장된 결과 없음",
    partial: "일부 데이터만 저장됨",
    fresh: "저장된 결과",
    stale: "저장된 결과 · 업데이트 필요",
  };
  const checked = formatCheckedAt(snapshot.checked_at);
  el("cache-status").textContent =
    `${labels[snapshot.cache] || ""}${checked ? ` · ${checked}` : ""}`;
}
```

`renderStoredSnapshot` 시작에서 `renderCacheStatus(snapshot)`을 호출한다.

```javascript
// renderActions에서 CSV button 다음에 추가
const refresh = document.createElement("button");
refresh.className = "btn";
refresh.textContent = "전체 새로고침";
refresh.addEventListener("click", () => scanComplex({ forceFull: true }));
bar.append(refresh);
```

- [ ] **Step 7: 전체 프런트엔드 helper 테스트와 Python 회귀 테스트를 실행한다**

Run: `node --test tests/test_frontend_cache.mjs`

Expected: 9 tests, 9 pass

Run: `python3 -m unittest discover -s tests -v`

Expected: `OK`, live 2 tests skipped

- [ ] **Step 8: 동시 갱신 UI 단위를 커밋한다**

```bash
git add public/index.html tests/test_frontend_cache.mjs
git commit -m "feat: 공유 캐시 갱신 상태와 전체 새로고침 추가"
```

---

### Task 8: 운영 문서와 전체 검증

**Files:**
- Modify: `README.md:6-29,92-120`
- Verify: `vercel.json`
- Verify: all changed files

**Interfaces:**
- Consumes: 완성된 캐시 API와 UI
- Produces: Upstash 연결·보안·갱신 정책 운영 문서, 검증 증거

- [ ] **Step 1: README에 Upstash 설치와 정책을 문서화한다**

````markdown
### 공유 캐시 연결

Vercel 프로젝트의 `Storage` 또는 `Marketplace`에서 Upstash Redis를 설치하고 프로젝트에
연결한다. 통합이 다음 환경변수를 자동으로 만든다.

```text
UPSTASH_REDIS_REST_URL
UPSTASH_REDIS_REST_TOKEN
```

연결 뒤에는 새 배포가 필요하다. 표준 토큰은 쓰기 권한이 있으므로 HTML, JavaScript, Git 저장소에
복사하지 않는다. 두 환경변수가 없거나 Redis에 연결할 수 없으면 앱은 공유 캐시를 건너뛰고 기존처럼
청약홈을 직접 조회한다.

저장된 `정보없음`과 `조회실패`는 24시간 뒤, 전체 동·호 구조와 `정보있음`은 7일 뒤 다시 확인한다.
사용자가 `전체 새로고침`을 누를 수도 있지만 같은 단지는 10분에 한 번만 시작한다. 90일 동안 아무도
조회하지 않은 단지 결과는 자동 삭제된다. 날짜별 변경 이력과 방문자 정보는 저장하지 않는다.
````

README 테스트 절의 `기본 실행은 74건`은 `기본 실행은 104건이며 그중 라이브 2건은 건너뛴다`로
바꾸고, `node --test tests/test_frontend_cache.mjs` 명령도 함께 추가한다.

- [ ] **Step 2: Python 문법과 전체 저장 fixture 테스트를 실행한다**

Run: `python3 -m py_compile api/_cache.py api/_lib.py api/cache.py`

Expected: no output, exit 0

Run: `python3 -m unittest discover -s tests -v`

Expected: 104 tests, `OK (skipped=2)`

Run: `python3 -m json.tool vercel.json`

Expected: formatted JSON output, exit 0

- [ ] **Step 3: 프런트엔드 모듈과 정적 계약을 검증한다**

Run: `node --check public/cache.mjs`

Expected: no output, exit 0

Run: `node --test tests/test_frontend_cache.mjs`

Expected: 9 tests, 9 pass

Run: `rg -n 'UPSTASH_REDIS_REST_TOKEN|UPSTASH_REDIS_REST_URL' public`

Expected: no matches

- [ ] **Step 4: 로컬 fail-open 동작을 검증한다**

Run: `env -u UPSTASH_REDIS_REST_URL -u UPSTASH_REDIS_REST_TOKEN python3 -m unittest tests.test_server_search -v`

Expected: `/api/cache`가 `cache: disabled`를 반환하는 테스트를 포함해 all tests `OK`

- [ ] **Step 5: diff와 비밀정보 유출을 검증한다**

Run: `git diff --check`

Expected: no output, exit 0

Run: `git diff --name-only`

Expected: `README.md`만 출력

Run: `rg -n 'Bearer [A-Za-z0-9_-]{16,}|upstash\.io' api public tests README.md`

Expected: 실제 토큰이나 실제 데이터베이스 endpoint 없음

- [ ] **Step 6: 문서와 최종 검증 단위를 커밋한다**

```bash
git add README.md api/_cache.py api/_lib.py api/cache.py public/cache.mjs public/index.html \
  server.py tests/test_cache.py tests/test_api.py tests/test_server_search.py \
  tests/test_frontend_cache.mjs
git commit -m "docs: 공유 캐시 배포와 갱신 정책 안내"
```

- [ ] **Step 7: 기존 draft PR 브랜치를 갱신한다**

Run: `git status --short --branch`

Expected: clean worktree, `feat/vercel-deploy` ahead of `origin/feat/vercel-deploy`

Run: `git push origin feat/vercel-deploy`

Expected: push succeeds and draft PR #1 receives the cache commits

- [ ] **Step 8: 실제 Vercel 배포에서 공유 여부를 확인한다**

GitHub push로 Production 또는 Preview가 재배포된 뒤 브라우저 A에서 단지 하나를 조회한다. 브라우저
B의 새 세션에서 같은 단지를 조회해 청약홈 전체 스캔 전에 저장 결과와 마지막 확인 시각이 표시되는지
확인한다. Upstash Console에서 `scan:v1:` 접두사의 Hash 하나와 90일 이하 TTL을 확인하고, 토큰 값
자체는 로그나 스크린샷에 남기지 않는다. 브라우저 B에서 CSV를 내려받아 UTF-8 BOM이 유지되고,
헤더를 제외한 행 수가 화면의 전체 세대 수와 같은지도 확인한다.
