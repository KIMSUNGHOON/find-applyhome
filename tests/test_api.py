import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api"))

import applyhome
import _cache
import _lib

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
NOW = 1_784_871_000
DAY = 86_400


def q(**kwargs):
    """parse_qs 형태로 만든다 — 값이 리스트다."""
    return {k: [v] for k, v in kwargs.items()}


class OneTest(unittest.TestCase):
    def test_첫_값을_꺼낸다(self):
        self.assertEqual(_lib.one(q(name="상봉"), "name"), "상봉")

    def test_없으면_기본값이다(self):
        self.assertEqual(_lib.one({}, "name"), "")
        self.assertEqual(_lib.one({}, "page", "1"), "1")


class SearchTest(unittest.TestCase):
    def setUp(self):
        self.original = applyhome.search_complexes
        self.received = {}

        def fake(name="", area="", sigungu="", page=1):
            self.received.update(name=name, area=area, sigungu=sigungu, page=page)
            return ([applyhome.Complex("2025000439", "2025000439", "상봉 센트럴 아이파크",
                                       "2025.09.19", "2025.10.14", "일반공급 : 1년")], 168)

        applyhome.search_complexes = fake

    def tearDown(self):
        applyhome.search_complexes = self.original

    def test_검색_결과를_돌려준다(self):
        status, body = _lib.search(q(name="상봉"))
        self.assertEqual(status, 200)
        self.assertEqual(body["total"], 168)
        self.assertEqual(body["complexes"][0]["name"], "상봉 센트럴 아이파크")
        self.assertEqual(body["complexes"][0]["house_manage_no"], "2025000439")

    def test_인자가_그대로_전달된다(self):
        _lib.search(q(name="상봉", area="서울", sigungu="중랑구", page="3"))
        self.assertEqual(self.received["area"], "서울")
        self.assertEqual(self.received["page"], 3)

    def test_페이지가_숫자가_아니면_1이다(self):
        _lib.search(q(name="상봉", page="abc"))
        self.assertEqual(self.received["page"], 1)

    def test_청약홈_실패는_502다(self):
        applyhome.search_complexes = lambda **kw: (_ for _ in ()).throw(
            applyhome.ApplyhomeError("연결 실패"))
        status, body = _lib.search(q(name="상봉"))
        self.assertEqual(status, 502)
        self.assertIn("message", body)


class DongsTest(unittest.TestCase):
    def setUp(self):
        self.original = applyhome.list_dongs

    def tearDown(self):
        applyhome.list_dongs = self.original

    def test_동_목록을_sn과_name으로_돌려준다(self):
        applyhome.list_dongs = lambda hm, pb: [applyhome.Dong(1, "101"), applyhome.Dong(2, "102")]
        status, body = _lib.dongs(q(hm="1", pb="1"))
        self.assertEqual(status, 200)
        self.assertEqual(body["dongs"], [{"sn": 1, "name": "101"}, {"sn": 2, "name": "102"}])

    def test_동이_없으면_빈_배열이다(self):
        applyhome.list_dongs = lambda hm, pb: []
        status, body = _lib.dongs(q(hm="1", pb="1"))
        self.assertEqual(status, 200)
        self.assertEqual(body["dongs"], [])

    def test_인자가_빠지면_400이다(self):
        status, _ = _lib.dongs(q(hm="1"))
        self.assertEqual(status, 400)

    def test_대기열이면_502다(self):
        applyhome.list_dongs = lambda hm, pb: (_ for _ in ()).throw(
            applyhome.BlockedError("대기열입니다"))
        status, body = _lib.dongs(q(hm="1", pb="1"))
        self.assertEqual(status, 502)
        self.assertIn("대기열", body["message"])


class HosTest(unittest.TestCase):
    def setUp(self):
        self.original = applyhome.list_hos

    def tearDown(self):
        applyhome.list_hos = self.original

    def test_호_목록과_격자를_돌려준다(self):
        applyhome.list_hos = lambda hm, pb, sn: [
            applyhome.Ho(1, "201"), applyhome.Ho(2, "305"), applyhome.Ho(3, "1105")]
        status, body = _lib.hos(q(hm="1", pb="1", sn="1"))
        self.assertEqual(status, 200)
        self.assertEqual(body["hos"], ["201", "305", "1105"])
        self.assertEqual(body["grid"]["cells"]["1105"], [11, "05"])

    def test_격자화가_안_되면_grid가_None이다(self):
        applyhome.list_hos = lambda hm, pb, sn: [applyhome.Ho(1, "1"), applyhome.Ho(2, "A2")]
        _, body = _lib.hos(q(hm="1", pb="1", sn="1"))
        self.assertIsNone(body["grid"])

    def test_sn이_숫자가_아니면_400이다(self):
        status, _ = _lib.hos(q(hm="1", pb="1", sn="abc"))
        self.assertEqual(status, 400)


class UnitTest(unittest.TestCase):
    def setUp(self):
        self.original = applyhome.fetch_detail

    def tearDown(self):
        applyhome.fetch_detail = self.original

    def test_세대_정보를_돌려준다(self):
        applyhome.fetch_detail = lambda hm, pb, d, h: applyhome.UnitDetail(
            d, h, "info", {"주택형": "084.8422A"})
        status, body = _lib.unit(q(hm="1", pb="1", dong="101", ho="201"))
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "info")
        self.assertEqual(body["fields"]["주택형"], "084.8422A")

    def test_실패해도_200에_error_상태다(self):
        # 개별 세대 실패가 스캔 전체를 멈추면 안 된다
        applyhome.fetch_detail = lambda hm, pb, d, h: (_ for _ in ()).throw(
            applyhome.ApplyhomeError("타임아웃"))
        status, body = _lib.unit(q(hm="1", pb="1", dong="101", ho="201"))
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "error")
        self.assertEqual(body["dong"], "101")
        self.assertEqual(body["ho"], "201")

    def test_인자가_빠지면_400이다(self):
        status, _ = _lib.unit(q(hm="1", pb="1", dong="101"))
        self.assertEqual(status, 400)


class PblancTest(unittest.TestCase):
    def setUp(self):
        self.original = applyhome.fetch_pblanc_supply

    def tearDown(self):
        applyhome.fetch_pblanc_supply = self.original

    def test_공고_정보에_축약과_전용면적이_붙는다(self):
        applyhome.fetch_pblanc_supply = lambda hm, pb: [
            applyhome.SupplyType("084.8422A", "116.9496", 22, 23, 45)]
        status, body = _lib.pblanc(q(hm="1", pb="1"))
        self.assertEqual(status, 200)
        s = body["supply"][0]
        self.assertEqual(s["type"], "084.8422A")
        self.assertEqual(s["short"], "84A")
        self.assertEqual(s["net_area"], "84.8422")
        self.assertEqual((s["general"], s["special"], s["total"]), (22, 23, 45))
        self.assertFalse(body["refresh_failed"])

    def test_공고가_없으면_supply가_None이다(self):
        applyhome.fetch_pblanc_supply = lambda hm, pb: []
        _, body = _lib.pblanc(q(hm="1", pb="1"))
        self.assertIsNone(body["supply"])
        self.assertFalse(body["refresh_failed"])

    def test_조회가_터져도_supply가_None이고_200이다(self):
        # 공고는 부가 정보다. 실패해도 스캔을 막지 않는다
        applyhome.fetch_pblanc_supply = lambda hm, pb: (_ for _ in ()).throw(RuntimeError("오류"))
        status, body = _lib.pblanc(q(hm="1", pb="1"))
        self.assertEqual(status, 200)
        self.assertIsNone(body["supply"])
        self.assertTrue(body["refresh_failed"])


class FakeCache:
    def __init__(self):
        self.calls = []
        self.snapshot = {
            "cache": "fresh",
            "complete": True,
            "checked_at": NOW,
            "meta": {"total": 0, "dongs": [], "supply": []},
            "units": [],
            "refresh": {
                "topology": False,
                "supply": False,
                "all_units": False,
                "units": [],
            },
        }
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

    def write_unit(self, hm, pb, unit, token):
        self.calls.append(("write_unit", hm, pb, unit, token))

    def claim_unit(self, hm, pb, dong, ho):
        return self.lock

    def release_unit(self, hm, pb, dong, ho, token):
        self.calls.append(("release_unit", token))

    def read_unit(self, hm, pb, dong, ho):
        return self.cached_unit

    def record_unit_error(self, hm, pb, dong, ho, message, token):
        self.calls.append(("record_unit_error", dong, ho, token))
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

    def test_cache_조회_예외은_disabled로_직접_조회를_지시한다(self):
        def broken_read(hm, pb, request_full=False):
            raise RuntimeError("redis secret detail")

        self.cache.read_snapshot = broken_read
        status, body = _lib.cache_snapshot(q(hm="1", pb="2"))
        self.assertEqual(status, 200)
        self.assertEqual(
            body,
            {
                "cache": "disabled",
                "complete": False,
                "checked_at": None,
                "meta": None,
                "units": [],
                "refresh": {
                    "topology": True,
                    "supply": True,
                    "all_units": True,
                    "units": [],
                },
                "full_refresh": {"allowed": True, "retry_after": 0},
            },
        )
        self.assertNotIn("secret", str(body))

    def test_dongs가_서버에서_받은_값을_write_through한다(self):
        original = applyhome.list_dongs
        applyhome.list_dongs = lambda hm, pb: [applyhome.Dong(1, "101")]
        try:
            _lib.dongs(q(hm="1", pb="2"))
        finally:
            applyhome.list_dongs = original
        self.assertIn(
            ("write_dongs", "1", "2", [{"sn": 1, "name": "101"}]),
            self.cache.calls,
        )

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

    def test_pblanc_조회_실패는_cache를_쓰지_않는다(self):
        original = applyhome.fetch_pblanc_supply
        applyhome.fetch_pblanc_supply = lambda hm, pb: (_ for _ in ()).throw(
            RuntimeError("상류 실패")
        )
        try:
            status, body = _lib.pblanc(q(hm="1", pb="2"))
        finally:
            applyhome.fetch_pblanc_supply = original
        self.assertEqual(status, 200)
        self.assertIsNone(body["supply"])
        self.assertTrue(body["refresh_failed"])
        self.assertFalse(any(call[0] == "write_supply" for call in self.cache.calls))

    def test_pblanc_성공_빈_결과는_None을_cache에_쓴다(self):
        original = applyhome.fetch_pblanc_supply
        applyhome.fetch_pblanc_supply = lambda hm, pb: []
        try:
            status, body = _lib.pblanc(q(hm="1", pb="2"))
        finally:
            applyhome.fetch_pblanc_supply = original
        self.assertEqual(status, 200)
        self.assertIsNone(body["supply"])
        self.assertFalse(body["refresh_failed"])
        self.assertIn(("write_supply", "1", "2", None), self.cache.calls)

    def test_unit_잠금_경합과_기존값은_200_refreshing이다(self):
        self.cache.lock = _cache.LockResult("busy")
        self.cache.cached_unit = {
            "dong": "101",
            "ho": "201",
            "status": "empty",
            "fields": {},
            "checked_at": NOW - DAY,
        }
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
            dong, ho, "info", {"주택형": "084.8422A"}
        )
        try:
            status, body = _lib.unit(q(hm="1", pb="2", dong="101", ho="201"))
        finally:
            applyhome.fetch_detail = original
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "info")
        self.assertTrue(any(
            call[0] == "write_unit" and call[-1] == "owner"
            for call in self.cache.calls
        ))
        self.assertIn(("release_unit", "owner"), self.cache.calls)

    def test_unit_실패도_소유자_토큰으로_오류를_기록한다(self):
        original = applyhome.fetch_detail
        applyhome.fetch_detail = lambda hm, pb, dong, ho: (_ for _ in ()).throw(
            applyhome.ApplyhomeError("타임아웃")
        )
        try:
            status, body = _lib.unit(q(hm="1", pb="2", dong="101", ho="201"))
        finally:
            applyhome.fetch_detail = original
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "error")
        self.assertIn(("record_unit_error", "101", "201", "owner"), self.cache.calls)
        self.assertIn(("release_unit", "owner"), self.cache.calls)


class RoutesTest(unittest.TestCase):
    def test_여섯_경로가_등록되어_있다(self):
        self.assertEqual(
            set(_lib.ROUTES),
            {
                "/api/search",
                "/api/dongs",
                "/api/hos",
                "/api/unit",
                "/api/pblanc",
                "/api/cache",
            },
        )


if __name__ == "__main__":
    unittest.main()
