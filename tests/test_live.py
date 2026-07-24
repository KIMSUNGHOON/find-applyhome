"""청약홈에 실제로 붙는 회귀 테스트.

2026-07-24 실측값을 기준으로 삼는다. 청약홈 데이터가 갱신되면 값이 달라질 수 있으므로
기본으로는 건너뛰고, APPLYHOME_LIVE=1 일 때만 돈다.

    APPLYHOME_LIVE=1 python3 -m unittest tests.test_live -v
"""

import os
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import applyhome
import scanner

LIVE = os.environ.get("APPLYHOME_LIVE") == "1"

SANGBONG = ("2025000439", "2025000439")
EXPECTED_EMPTY_101 = {"305", "502", "603", "1105", "1401", "1404", "1405", "2004", "2302", "2303"}


@unittest.skipUnless(LIVE, "APPLYHOME_LIVE=1 일 때만 실행합니다")
class LiveTest(unittest.TestCase):
    def test_상봉_101동_정보없음_10건이_그대로다(self):
        hm, pb = SANGBONG
        events = []
        scanner.scan_complex(hm, pb, lambda name, payload: events.append((name, payload)))

        units = [payload for name, payload in events if name == "unit"]
        dong_101 = [u for u in units if u["dong"] == "101"]
        self.assertEqual(len(dong_101), 119, "101동 세대 수가 119가 아닙니다")

        empties = {u["ho"] for u in dong_101 if u["status"] == "empty"}
        self.assertEqual(empties, EXPECTED_EMPTY_101)

    def test_장위_1001동_201호는_정보가_있다(self):
        unit = applyhome.fetch_detail("2026000275", "2026000275", "1001", "201")
        self.assertEqual(unit.status, "info")
        self.assertEqual(unit.fields["주택명"], "장위 푸르지오 마크원")


if __name__ == "__main__":
    unittest.main()
