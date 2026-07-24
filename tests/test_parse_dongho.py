import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import applyhome

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


class ParseDongListTest(unittest.TestCase):
    def test_동_23개를_뽑는다(self):
        raw = (FIXTURES / "donglist_jangwi.json").read_text(encoding="utf-8")
        dongs = applyhome.parse_dong_list(raw)
        self.assertEqual(len(dongs), 23)

    def test_첫_동은_sn과_name이_다르다(self):
        raw = (FIXTURES / "donglist_jangwi.json").read_text(encoding="utf-8")
        first = applyhome.parse_dong_list(raw)[0]
        self.assertEqual(first.sn, 1)
        self.assertEqual(first.name, "1001")

    def test_JSON이_아니면_BlockedError(self):
        with self.assertRaises(applyhome.BlockedError):
            applyhome.parse_dong_list("<html>대기열 안내</html>")


class ParseHoListTest(unittest.TestCase):
    def test_장위_1001동은_18호(self):
        raw = (FIXTURES / "holist_jangwi_dong1.json").read_text(encoding="utf-8")
        self.assertEqual(len(applyhome.parse_ho_list(raw)), 18)

    def test_상봉_101동은_119호(self):
        raw = (FIXTURES / "holist_sangbong_dong1.json").read_text(encoding="utf-8")
        self.assertEqual(len(applyhome.parse_ho_list(raw)), 119)

    def test_호수는_문자열로_변환된다(self):
        raw = (FIXTURES / "holist_jangwi_dong1.json").read_text(encoding="utf-8")
        first = applyhome.parse_ho_list(raw)[0]
        self.assertIsInstance(first.no, str)
        self.assertEqual(first.no, "201")

    def test_JSON이_아니면_BlockedError(self):
        with self.assertRaises(applyhome.BlockedError):
            applyhome.parse_ho_list("서비스 점검 중입니다")


if __name__ == "__main__":
    unittest.main()
