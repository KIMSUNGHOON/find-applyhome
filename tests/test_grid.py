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


if __name__ == "__main__":
    unittest.main()
