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
