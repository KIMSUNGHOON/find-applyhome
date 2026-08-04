import json
import pathlib
import sys
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import _cache

NOW = 1_784_871_000
DAY = 24 * 60 * 60
WEEK = 7 * DAY

# 2026-08-03T15:00:00Z 가 KST 2026-08-04T00:00:00 이다. 경계 직전은 1초 뒤가 아니라 1초 앞이다.
VISIT_NOW = 1785812400          # 2026-08-04 12:00 KST
KST_MIDNIGHT = 1785769200       # 2026-08-04 00:00 KST
KST_BEFORE_MIDNIGHT = 1785769199  # 2026-08-03 23:59:59 KST


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def complete_raw(unit_status="info", unit_checked_at=NOW):
    return {
        "_dongs": encoded({"dongs": [{"sn": 1, "name": "101"}], "checked_at": NOW}),
        "t:1": encoded({
            "sn": 1,
            "hos": ["201"],
            "grid": {
                "floors": [2],
                "lines": ["01"],
                "cells": {"201": [2, "01"]},
            },
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


class KstDateTest(unittest.TestCase):
    def test_UTC_15시가_되면_KST_다음날이다(self):
        self.assertEqual(_cache.kst_date(KST_MIDNIGHT), "2026-08-04")

    def test_UTC_15시_직전은_KST_같은날이다(self):
        self.assertEqual(_cache.kst_date(KST_BEFORE_MIDNIGHT), "2026-08-03")

    def test_낮_시각도_같은_날짜다(self):
        self.assertEqual(_cache.kst_date(VISIT_NOW), "2026-08-04")

    def test_날짜키는_KST_날짜로_만든다(self):
        self.assertEqual(_cache.visit_day_key("2026-08-04"), "visits:day:2026-08-04")

    def test_길이가_어긋난_날짜는_거부한다(self):
        with self.assertRaises(ValueError):
            _cache.visit_day_key("2026-08-04T00:00:00")


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

    def test_info는_topology와_독립적으로_7일마다_재확인한다(self):
        result = _cache.assemble_snapshot(complete_raw("info", NOW - WEEK), NOW)
        self.assertEqual(result.payload["cache"], "stale")
        self.assertEqual(result.payload["refresh"]["units"], [{"dong": "101", "ho": "201"}])

    def test_허용되지_않은_호실_상태는_partial로_복구한다(self):
        result = _cache.assemble_snapshot(complete_raw("unknown"), NOW)
        self.assertEqual(result.payload["cache"], "partial")
        self.assertFalse(result.payload["complete"])
        self.assertEqual(result.payload["units"], [])
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

    def test_dongs_record의_식별자나_timestamp가_손상되면_topology를_다시_읽는다(self):
        malformed = [
            {"dongs": [{"sn": True, "name": "101"}], "checked_at": NOW},
            {"dongs": [{"sn": 10**40, "name": "101"}], "checked_at": NOW},
            {"dongs": [{"sn": 1, "name": None}], "checked_at": NOW},
            {"dongs": [{"sn": 1, "name": "101\n"}], "checked_at": NOW},
            {"dongs": [{"sn": 1, "name": "101"}], "checked_at": "now"},
            {"dongs": [{"sn": 1, "name": "101"}], "checked_at": NOW + 1},
        ]
        for record in malformed:
            with self.subTest(record=record):
                raw = complete_raw()
                raw["_dongs"] = encoded(record)
                result = _cache.assemble_snapshot(raw, NOW)
                self.assertEqual(result.payload["cache"], "partial")
                self.assertIsNone(result.payload["meta"])
                self.assertTrue(result.payload["refresh"]["topology"])

    def test_topology_record의_연결_식별자와_구조가_손상되면_partial이다(self):
        malformed = [
            {"sn": 2, "hos": ["201"], "grid": None, "checked_at": NOW},
            {"sn": True, "hos": ["201"], "grid": None, "checked_at": NOW},
            {"sn": 1, "hos": None, "grid": None, "checked_at": NOW},
            {"sn": 1, "hos": [201], "grid": None, "checked_at": NOW},
            {"sn": 1, "hos": ["201"], "grid": [], "checked_at": NOW},
            {"sn": 1, "hos": ["201"], "grid": {
                "floors": [2], "lines": ["01"], "cells": {"999": [2, "01"]},
            }, "checked_at": NOW},
            {"sn": 1, "hos": ["201"], "grid": None, "checked_at": 1.5},
        ]
        for record in malformed:
            with self.subTest(record=record):
                raw = complete_raw()
                raw["t:1"] = encoded(record)
                result = _cache.assemble_snapshot(raw, NOW)
                self.assertEqual(result.payload["cache"], "partial")
                self.assertFalse(result.payload["complete"])
                self.assertTrue(result.payload["refresh"]["topology"])

    def test_supply_null은_유효한_당일_record로_보존한다(self):
        raw = complete_raw()
        raw["_supply"] = encoded({"supply": None, "checked_at": NOW})
        result = _cache.assemble_snapshot(raw, NOW)
        self.assertEqual(result.payload["cache"], "fresh")
        self.assertIsNone(result.payload["meta"]["supply"])
        self.assertFalse(result.payload["refresh"]["supply"])

    def test_supply_record의_구조나_timestamp가_손상되면_공급정보를_다시_읽는다(self):
        malformed = [
            {"supply": {}, "checked_at": NOW},
            {"supply": [{"type": "084.0"}], "checked_at": NOW},
            {"supply": [{
                "type": "084.0", "short": "84", "net_area": "84.0", "area": "100.0",
                "general": "1", "special": 2, "total": 3,
            }], "checked_at": NOW},
            {"supply": [], "checked_at": False},
        ]
        for record in malformed:
            with self.subTest(record=record):
                raw = complete_raw()
                raw["_supply"] = encoded(record)
                result = _cache.assemble_snapshot(raw, NOW)
                self.assertEqual(result.payload["cache"], "stale")
                self.assertTrue(result.payload["complete"])
                self.assertIsNone(result.payload["meta"]["supply"])
                self.assertTrue(result.payload["refresh"]["supply"])

    def test_unit_record의_식별자_fields_timestamp가_손상되면_누락으로_취급한다(self):
        malformed = [
            {"dong": "102", "ho": "201", "status": "info",
             "fields": {}, "checked_at": NOW},
            {"dong": "101", "ho": "202", "status": "info",
             "fields": {}, "checked_at": NOW},
            {"dong": "101", "ho": "201", "status": [],
             "fields": {}, "checked_at": NOW},
            {"dong": "101", "ho": "201", "status": "info",
             "fields": None, "checked_at": NOW},
            {"dong": "101", "ho": "201", "status": "info",
             "fields": {"주택형": ["084.0"]}, "checked_at": NOW},
            {"dong": "101", "ho": "201", "status": "info",
             "fields": {}, "checked_at": "now"},
            {"dong": "101", "ho": "201", "status": "info",
             "fields": {}, "checked_at": NOW, "last_error_at": NOW + 1,
             "last_error": "최근 갱신에 실패했습니다."},
        ]
        field = _cache.unit_field("101", "201")
        for record in malformed:
            with self.subTest(record=record):
                raw = complete_raw()
                raw[field] = encoded(record)
                result = _cache.assemble_snapshot(raw, NOW)
                self.assertEqual(result.payload["cache"], "partial")
                self.assertEqual(result.payload["units"], [])
                self.assertEqual(
                    result.payload["refresh"]["units"],
                    [{"dong": "101", "ho": "201"}],
                )

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


class CountVisitTest(unittest.TestCase):
    def store(self, transport):
        return _cache.CacheStore(transport, now=lambda: VISIT_NOW)

    def test_어제_방문자는_오늘_처음이라_1을_더한다(self):
        transport = FakeTransport([[3456, 12, 1]])
        result = self.store(transport).count_visit("2026-08-03")
        self.assertEqual(result, {"today": "2026-08-04", "day": 12, "total": 3456})
        self.assertEqual(transport.calls[0], [
            ["INCRBY", "visits:total", 1],
            ["INCRBY", "visits:day:2026-08-04", 1],
            ["EXPIRE", "visits:day:2026-08-04", 172800],
        ])

    def test_오늘_이미_센_방문자는_0을_더한다(self):
        transport = FakeTransport([[3456, 12, 1]])
        result = self.store(transport).count_visit("2026-08-04")
        self.assertEqual(result, {"today": "2026-08-04", "day": 12, "total": 3456})
        self.assertEqual(transport.calls[0], [
            ["INCRBY", "visits:total", 0],
            ["INCRBY", "visits:day:2026-08-04", 0],
            ["EXPIRE", "visits:day:2026-08-04", 172800],
        ])

    def test_last가_없으면_새_방문자로_센다(self):
        transport = FakeTransport([[1, 1, 1]])
        self.store(transport).count_visit("")
        self.assertEqual(transport.calls[0][0][2], 1)

    def test_이상한_last는_키를_오염시키지_않는다(self):
        transport = FakeTransport([[1, 1, 1]])
        self.store(transport).count_visit("../../etc/passwd")
        self.assertEqual(transport.calls[0][1][1], "visits:day:2026-08-04")
        self.assertEqual(transport.calls[0][0][2], 1)

    def test_Redis가_죽으면_None이다(self):
        transport = FakeTransport([_cache.CacheUnavailable("down")])
        self.assertIsNone(self.store(transport).count_visit("2026-08-03"))

    def test_형식이_어긋난_응답은_None이다(self):
        transport = FakeTransport([[None, None, 1]])
        self.assertIsNone(self.store(transport).count_visit("2026-08-03"))

    def test_응답_개수가_모자라면_None이다(self):
        transport = FakeTransport([[3456]])
        self.assertIsNone(self.store(transport).count_visit("2026-08-03"))


class LeaseRaceTransport:
    """호실 잠금과 Hash 한 필드만 실제 Redis처럼 유지하는 테스트 전송 계층."""

    def __init__(self, lock_owner, unit):
        self.lock_owner = lock_owner
        self.unit = dict(unit)
        self.calls = []

    def pipeline(self, commands):
        self.calls.append(commands)
        results = []
        for command in commands:
            operation = command[0]
            if operation == "HGET":
                results.append(encoded(self.unit))
            elif operation == "HSET":
                self.unit = json.loads(command[3])
                results.append(1)
            elif operation == "EXPIRE":
                results.append(1)
            elif operation == "EVAL" and command[2] == 2:
                token, _, value, _ = command[5:]
                if self.lock_owner != token:
                    results.append(0)
                    continue
                self.unit = json.loads(value)
                results.append(1)
            else:
                raise AssertionError(f"지원하지 않는 Redis 명령: {command!r}")
        return results


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return self.payload


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

    def test_사라진_전체_새로고침_cooldown은_한번_더_획득한다(self):
        transport = FakeTransport([[None, -2], ["OK", 600]])
        store = _cache.CacheStore(transport, now=lambda: NOW)
        self.assertEqual(store.claim_full_refresh("1", "2"),
                         {"allowed": True, "retry_after": 0})
        self.assertEqual(len(transport.calls), 2)

    def test_사라진_전체_새로고침_cooldown은_재시도를_한번으로_제한한다(self):
        transport = FakeTransport([[None, -2], [None, -2]])
        store = _cache.CacheStore(transport, now=lambda: NOW)
        self.assertEqual(store.claim_full_refresh("1", "2"),
                         {"allowed": True, "retry_after": 0})
        self.assertEqual(len(transport.calls), 2)

    def test_정상값_재확인_실패는_상태를_보존한다(self):
        old = {"dong": "101", "ho": "201", "status": "info",
               "fields": {"주택형": "084.8422A"}, "checked_at": NOW - WEEK}
        transport = FakeTransport([[
            json.dumps(old, ensure_ascii=False)
        ], [1]])
        store = _cache.CacheStore(transport, now=lambda: NOW)
        saved = store.record_unit_error("1", "2", "101", "201", "타임아웃", "owner")
        self.assertEqual(saved["status"], "info")
        self.assertEqual(saved["last_error_at"], NOW)
        self.assertNotIn("타임아웃", json.dumps(transport.calls))

    def test_첫_조회_실패는_error로_저장한다(self):
        transport = FakeTransport([[None], [1]])
        store = _cache.CacheStore(transport, now=lambda: NOW)
        saved = store.record_unit_error("1", "2", "101", "201", "타임아웃", "owner")
        self.assertEqual(saved["status"], "error")
        self.assertEqual(saved["fields"], {})

    def test_비객체_호실_JSON은_오류_기록에서_처음_실패로_처리한다(self):
        transport = FakeTransport([["1"], [1]])
        store = _cache.CacheStore(transport, now=lambda: NOW)
        saved = store.record_unit_error("1", "2", "101", "201", "타임아웃", "owner")
        self.assertEqual(saved["status"], "error")
        self.assertEqual(saved["fields"], {})

    def test_read_unit은_요청과_일치하는_정상_record만_반환한다(self):
        valid = {
            "dong": "101", "ho": "201", "status": "info",
            "fields": {"주택형": "084.0"}, "checked_at": NOW,
        }
        store = _cache.CacheStore(
            FakeTransport([[encoded(valid)]]), now=lambda: NOW,
        )
        self.assertEqual(store.read_unit("1", "2", "101", "201"), valid)

    def test_read_unit은_식별자_status_fields_timestamp가_손상된_record를_숨긴다(self):
        malformed = [
            {"dong": "102", "ho": "201", "status": "info",
             "fields": {}, "checked_at": NOW},
            {"dong": "101", "ho": "201", "status": "unknown",
             "fields": {}, "checked_at": NOW},
            {"dong": "101", "ho": "201", "status": [],
             "fields": {}, "checked_at": NOW},
            {"dong": "101", "ho": "201", "status": "info",
             "fields": None, "checked_at": NOW},
            {"dong": "101", "ho": "201", "status": "info",
             "fields": {}, "checked_at": -1},
        ]
        for record in malformed:
            with self.subTest(record=record):
                store = _cache.CacheStore(
                    FakeTransport([[encoded(record)]]), now=lambda: NOW,
                )
                self.assertIsNone(store.read_unit("1", "2", "101", "201"))

    def test_만료된_잠금의_이전_소유자는_새_성공값을_덮어쓰지_못한다(self):
        newer = {
            "dong": "101", "ho": "201", "status": "info",
            "fields": {"주택형": "새 값"}, "checked_at": NOW,
        }
        transport = LeaseRaceTransport("second-owner", newer)
        store = _cache.CacheStore(transport, now=lambda: NOW + 1)

        written = store.write_unit(
            "1", "2",
            {"dong": "101", "ho": "201", "status": "empty", "fields": {}},
            "first-owner",
        )

        self.assertFalse(written)
        self.assertEqual(transport.unit, newer)

    def test_만료된_잠금의_이전_소유자는_새_성공값에_늦은_오류를_기록하지_못한다(self):
        newer = {
            "dong": "101", "ho": "201", "status": "info",
            "fields": {"주택형": "새 값"}, "checked_at": NOW,
        }
        transport = LeaseRaceTransport("second-owner", newer)
        store = _cache.CacheStore(transport, now=lambda: NOW + 1)

        saved = store.record_unit_error(
            "1", "2", "101", "201", "타임아웃", "first-owner",
        )

        self.assertEqual(saved["status"], "info")
        self.assertEqual(transport.unit, newer)


class PersistenceTest(unittest.TestCase):
    def test_result_없는_REST_응답은_회로를_차단한다(self):
        clock = iter([10.0, 10.0, 20.0])
        with patch.object(_cache.urllib.request, "urlopen",
                          return_value=FakeResponse([{}])) as urlopen:
            transport = _cache.UpstashTransport(
                "https://redis.example", "secret", monotonic=lambda: next(clock))
            with self.assertRaises(_cache.CacheUnavailable):
                transport.pipeline([["PING"]])
            with self.assertRaises(_cache.CacheUnavailable):
                transport.pipeline([["PING"]])

        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://redis.example/pipeline")
        self.assertEqual(request.data, b'[["PING"]]')
        self.assertEqual(request.get_header("Authorization"), "Bearer secret")
        self.assertEqual(urlopen.call_args.kwargs["timeout"], _cache.REDIS_TIMEOUT)
        self.assertEqual(urlopen.call_count, 1)

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
        transport = FakeTransport([[1]])
        store = _cache.CacheStore(transport, now=lambda: NOW)
        store.write_unit("1", "2", {"dong": "101", "ho": "201",
                                      "status": "empty", "fields": {}}, "owner")
        command = transport.calls[0][0]
        self.assertEqual(command[:3], ["EVAL", _cache._WRITE_UNIT_SCRIPT, 2])
        self.assertEqual(command[3:7], [
            "lock:scan:v1:1:2:101:201", "scan:v1:1:2", "owner", "u:101:201",
        ])
        saved = json.loads(command[7])
        self.assertEqual(saved["checked_at"], NOW)
        self.assertEqual(command[8], _cache.CACHE_TTL)

    def test_허용되지_않은_호실_상태는_저장하지_않는다(self):
        transport = FakeTransport()
        store = _cache.CacheStore(transport, now=lambda: NOW)
        written = store.write_unit("1", "2", {"dong": "101", "ho": "201",
                                                "status": "unknown", "fields": {}},
                                   "owner")
        self.assertFalse(written)
        self.assertEqual(transport.calls, [])

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
