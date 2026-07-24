import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import applyhome

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


class ParseComplexListTest(unittest.TestCase):
    def setUp(self):
        self.html = (FIXTURES / "list_seoul_p1.html").read_text(encoding="utf-8")

    def test_총건수를_읽는다(self):
        _, total = applyhome.parse_complex_list(self.html)
        self.assertEqual(total, 168)

    def test_한_페이지에서_단지_10건을_뽑는다(self):
        rows, _ = applyhome.parse_complex_list(self.html)
        self.assertEqual(len(rows), 10)

    def test_첫_단지의_필드가_정확하다(self):
        rows, _ = applyhome.parse_complex_list(self.html)
        first = rows[0]
        self.assertEqual(first.name, "장위 푸르지오 마크원")
        self.assertEqual(first.house_manage_no, "2026000275")
        self.assertEqual(first.pblanc_no, "2026000275")
        self.assertEqual(first.notice_date, "2026.06.19")
        self.assertEqual(first.winner_date, "2026.07.08")
        self.assertIn("특별공급", first.resale_limit)

    def test_모든_단지가_관리번호를_가진다(self):
        rows, _ = applyhome.parse_complex_list(self.html)
        for row in rows:
            self.assertTrue(row.house_manage_no.isdigit(), row.name)
            self.assertTrue(row.name)


class NormalizeLabelTest(unittest.TestCase):
    def test_각주_기호를_제거한다(self):
        self.assertEqual(applyhome._normalize_label("분양금액(만원)***"), "분양금액(만원)")
        self.assertEqual(applyhome._normalize_label("특이사항 **"), "특이사항")
        self.assertEqual(applyhome._normalize_label("추가입주 계약체결일 *"), "추가입주 계약체결일")
        self.assertEqual(applyhome._normalize_label("공고일"), "공고일")


if __name__ == "__main__":
    unittest.main()
