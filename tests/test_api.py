import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api"))

import applyhome
import _lib

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


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

    def test_공고가_없으면_supply가_None이다(self):
        applyhome.fetch_pblanc_supply = lambda hm, pb: []
        _, body = _lib.pblanc(q(hm="1", pb="1"))
        self.assertIsNone(body["supply"])

    def test_조회가_터져도_supply가_None이고_200이다(self):
        # 공고는 부가 정보다. 실패해도 스캔을 막지 않는다
        applyhome.fetch_pblanc_supply = lambda hm, pb: (_ for _ in ()).throw(RuntimeError("오류"))
        status, body = _lib.pblanc(q(hm="1", pb="1"))
        self.assertEqual(status, 200)
        self.assertIsNone(body["supply"])


class RoutesTest(unittest.TestCase):
    def test_다섯_경로가_등록되어_있다(self):
        self.assertEqual(
            set(_lib.ROUTES),
            {"/api/search", "/api/dongs", "/api/hos", "/api/unit", "/api/pblanc"},
        )


if __name__ == "__main__":
    unittest.main()
