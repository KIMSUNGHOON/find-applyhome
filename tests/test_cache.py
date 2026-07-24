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
        transport = FakeTransport([[1, 1]])
        store = _cache.CacheStore(transport, now=lambda: NOW)
        store.write_unit("1", "2", {"dong": "101", "ho": "201",
                                      "status": "empty", "fields": {}})
        commands = transport.calls[0]
        self.assertEqual(commands[0][:3], ["HSET", "scan:v1:1:2", "u:101:201"])
        saved = json.loads(commands[0][3])
        self.assertEqual(saved["checked_at"], NOW)
        self.assertEqual(commands[1], ["EXPIRE", "scan:v1:1:2", _cache.CACHE_TTL])

    def test_허용되지_않은_호실_상태는_저장하지_않는다(self):
        transport = FakeTransport()
        store = _cache.CacheStore(transport, now=lambda: NOW)
        written = store.write_unit("1", "2", {"dong": "101", "ho": "201",
                                                "status": "unknown", "fields": {}})
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
