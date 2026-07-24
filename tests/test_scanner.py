import pathlib
import sys
import threading
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import applyhome
import scanner


class FakeClient:
    """네트워크 없이 scanner 를 돌리기 위한 대역."""

    BlockedError = applyhome.BlockedError
    ApplyhomeError = applyhome.ApplyhomeError
    UnitDetail = applyhome.UnitDetail

    def __init__(self, dongs, hos, empty_hos=(), error_hos=()):
        self._dongs = dongs
        self._hos = hos
        self._empty = set(empty_hos)
        self._error = set(error_hos)

    def list_dongs(self, hm, pb):
        return self._dongs

    def list_hos(self, hm, pb, dong_sn):
        return self._hos[dong_sn]

    def fetch_detail(self, hm, pb, dong_name, ho_no):
        if (dong_name, ho_no) in self._error:
            raise applyhome.ApplyhomeError("일부러 낸 실패")
        if (dong_name, ho_no) in self._empty:
            return applyhome.UnitDetail(dong_name, ho_no, "empty", {})
        return applyhome.UnitDetail(dong_name, ho_no, "info", {"주택형": "084.9721"})


def collect(client, **kwargs):
    events = []
    scanner.scan_complex(
        "1", "1", lambda name, payload: events.append((name, payload)),
        client=client, delay=0, **kwargs
    )
    return events


class ScanComplexTest(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient(
            dongs=[applyhome.Dong(1, "101")],
            hos={1: [applyhome.Ho(1, "201"), applyhome.Ho(2, "202"), applyhome.Ho(3, "301")]},
            empty_hos={("101", "202")},
        )

    def test_meta가_가장_먼저_나온다(self):
        events = collect(self.client)
        self.assertEqual(events[0][0], "meta")
        self.assertEqual(events[0][1]["total"], 3)

    def test_meta에_동별_호목록과_격자가_들어있다(self):
        events = collect(self.client)
        dong = events[0][1]["dongs"][0]
        self.assertEqual(dong["name"], "101")
        self.assertEqual(dong["hos"], ["201", "202", "301"])
        self.assertEqual(dong["grid"]["cells"]["301"], [3, "01"])

    def test_done이_마지막이며_집계가_맞다(self):
        events = collect(self.client)
        name, payload = events[-1]
        self.assertEqual(name, "done")
        self.assertEqual(payload["total"], 3)
        self.assertEqual(payload["info"], 2)
        self.assertEqual(payload["empty"], 1)
        self.assertEqual(payload["error"], 0)

    def test_세대마다_unit_이벤트가_한번씩_나온다(self):
        events = collect(self.client)
        units = [payload for name, payload in events if name == "unit"]
        self.assertEqual(len(units), 3)
        self.assertEqual({u["ho"] for u in units}, {"201", "202", "301"})

    def test_empty_세대가_표시된다(self):
        events = collect(self.client)
        empties = [p for n, p in events if n == "unit" and p["status"] == "empty"]
        self.assertEqual(len(empties), 1)
        self.assertEqual(empties[0]["ho"], "202")

    def test_조회_실패는_error_상태로_담기고_스캔은_계속된다(self):
        client = FakeClient(
            dongs=[applyhome.Dong(1, "101")],
            hos={1: [applyhome.Ho(1, "201"), applyhome.Ho(2, "202")]},
            error_hos={("101", "202")},
        )
        events = collect(client)
        self.assertEqual(events[-1][0], "done")
        self.assertEqual(events[-1][1]["error"], 1)
        self.assertEqual(events[-1][1]["info"], 1)


class ScanFailureTest(unittest.TestCase):
    def test_동목록이_비면_error를_내고_끝낸다(self):
        client = FakeClient(dongs=[], hos={})
        events = collect(client)
        self.assertEqual(events[0][0], "error")
        self.assertIn("등록", events[0][1]["message"])

    def test_대기열이면_error를_낸다(self):
        class Blocked(FakeClient):
            def list_dongs(self, hm, pb):
                raise applyhome.BlockedError("대기열입니다")

        events = collect(Blocked(dongs=[], hos={}))
        self.assertEqual(events[0][0], "error")
        self.assertIn("대기열", events[0][1]["message"])


class StopTest(unittest.TestCase):
    def test_stop이_설정되면_done을_내지_않고_멈춘다(self):
        stop = threading.Event()
        stop.set()
        client = FakeClient(
            dongs=[applyhome.Dong(1, "101")],
            hos={1: [applyhome.Ho(1, "201")]},
        )
        events = collect(client, stop=stop)
        self.assertNotIn("done", [name for name, _ in events])


if __name__ == "__main__":
    unittest.main()
