import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import grid


class BuildGridTest(unittest.TestCase):
    def test_마지막_두자리가_라인이고_그_앞이_층이다(self):
        result = grid.build_grid(["201", "305", "1105"])
        self.assertEqual(result["cells"]["201"], [2, "01"])
        self.assertEqual(result["cells"]["305"], [3, "05"])
        self.assertEqual(result["cells"]["1105"], [11, "05"])

    def test_층은_내림차순_라인은_오름차순이다(self):
        result = grid.build_grid(["201", "305", "1105"])
        self.assertEqual(result["floors"], [11, 3, 2])
        self.assertEqual(result["lines"], ["01", "05"])

    def test_같은_층의_여러_라인을_모두_담는다(self):
        result = grid.build_grid(["301", "302", "303"])
        self.assertEqual(result["floors"], [3])
        self.assertEqual(result["lines"], ["01", "02", "03"])

    def test_세자리_미만이_섞이면_격자를_포기한다(self):
        self.assertIsNone(grid.build_grid(["1", "305"]))

    def test_숫자가_아닌_호수가_섞이면_격자를_포기한다(self):
        self.assertIsNone(grid.build_grid(["A2", "305"]))

    def test_빈_목록은_격자를_포기한다(self):
        self.assertIsNone(grid.build_grid([]))

    def test_상봉_101동_119호가_격자화된다(self):
        import json

        raw = json.loads(
            (pathlib.Path(__file__).parent / "fixtures" / "holist_sangbong_dong1.json")
            .read_text(encoding="utf-8")
        )
        hos = [str(item["HO_CO"]) for item in raw["holist"]]
        result = grid.build_grid(hos)
        self.assertIsNotNone(result)
        self.assertEqual(len(result["cells"]), 119)


class ShortTypeTest(unittest.TestCase):
    def test_전용면적_정수부와_타입코드를_붙인다(self):
        self.assertEqual(grid.short_type("084.8422A"), "84A")
        self.assertEqual(grid.short_type("039.7700A"), "39A")

    def test_타입코드가_없으면_숫자만_남는다(self):
        self.assertEqual(grid.short_type("046.8700"), "46")
        self.assertEqual(grid.short_type("114.2100"), "114")

    def test_두글자_타입코드도_유지한다(self):
        self.assertEqual(grid.short_type("059.9800A1"), "59A1")

    def test_형식이_다르면_입력을_그대로_돌려준다(self):
        self.assertEqual(grid.short_type("알수없음"), "알수없음")
        self.assertEqual(grid.short_type(""), "")


class NetAreaTest(unittest.TestCase):
    def test_앞자리_0을_버린_전용면적을_뽑는다(self):
        self.assertEqual(grid.net_area("084.8422A"), "84.8422")
        self.assertEqual(grid.net_area("046.8700"), "46.8700")
        self.assertEqual(grid.net_area("114.2100"), "114.2100")

    def test_형식이_다르면_빈_문자열이다(self):
        self.assertEqual(grid.net_area("알수없음"), "")


if __name__ == "__main__":
    unittest.main()
