import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import applyhome

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


class ParseSangbongTest(unittest.TestCase):
    def setUp(self):
        html = (FIXTURES / "pblanc_sangbong.html").read_text(encoding="utf-8")
        self.types = applyhome.parse_pblanc_supply(html)
        self.by_type = {t.house_type: t for t in self.types}

    def test_타입_5개를_뽑는다(self):
        self.assertEqual(len(self.types), 5)

    def test_타입별_일반_특별_계가_정확하다(self):
        a = self.by_type["084.8422A"]
        self.assertEqual((a.general, a.special, a.total), (22, 23, 45))
        c = self.by_type["084.6747C"]
        self.assertEqual((c.general, c.special, c.total), (23, 28, 51))

    def test_공급면적을_담는다(self):
        self.assertEqual(self.by_type["084.8422A"].area, "116.9496")

    def test_합계가_공고_공급규모와_같다(self):
        self.assertEqual(sum(t.total for t in self.types), 242)
        self.assertEqual(sum(t.general for t in self.types), 113)
        self.assertEqual(sum(t.special for t in self.types), 129)

    def test_계_행은_타입으로_잡히지_않는다(self):
        for t in self.types:
            self.assertRegex(t.house_type, r"^\d{2,4}\.\d{2,6}")

    def test_주택구분_rowspan이_있는_첫행도_정확하다(self):
        # 첫 행에만 '민영' 이 붙어 셀이 하나 더 많다
        self.assertEqual(self.by_type["084.8422A"].total, 45)
        self.assertEqual(self.by_type["084.7662B"].total, 49)


class SpecialSupplyTableTest(unittest.TestCase):
    """'입주자모집공고 특별공급 공급대상' 표에 오염되지 않아야 한다."""

    def test_특별공급_세부표가_섞이지_않는다(self):
        html = (FIXTURES / "pblanc_sangbong.html").read_text(encoding="utf-8")
        types = applyhome.parse_pblanc_supply(html)
        # 세부표가 섞이면 타입이 10개가 되고 합계가 242 를 벗어난다
        self.assertEqual(len(types), 5)
        self.assertEqual(sum(t.total for t in types), 242)


class ParseJangwiTest(unittest.TestCase):
    def setUp(self):
        html = (FIXTURES / "pblanc_jangwi.html").read_text(encoding="utf-8")
        self.types = applyhome.parse_pblanc_supply(html)
        self.by_type = {t.house_type: t for t in self.types}

    def test_타입_18개와_합계_1032(self):
        self.assertEqual(len(self.types), 18)
        self.assertEqual(sum(t.total for t in self.types), 1032)

    def test_타입코드가_없는_주택형도_담는다(self):
        t = self.by_type["046.8700"]
        self.assertEqual((t.general, t.special, t.total), (6, 1, 7))

    def test_세자리_세대수도_정확하다(self):
        t = self.by_type["084.8700B"]
        self.assertEqual((t.general, t.special, t.total), (115, 136, 251))


class FailureToleranceTest(unittest.TestCase):
    def test_빈_HTML은_빈_리스트다(self):
        self.assertEqual(applyhome.parse_pblanc_supply(""), [])

    def test_캡션이_없으면_빈_리스트다(self):
        html = "<html><table><caption>다른 표</caption><tr><td>x</td></tr></table></html>"
        self.assertEqual(applyhome.parse_pblanc_supply(html), [])

    def test_숫자가_아닌_세대수는_건너뛴다(self):
        html = (
            "<table><caption>입주자모집공고 공급대상</caption>"
            "<tr><td>084.1111A</td><td>100.0</td><td>미정</td><td>미정</td><td>미정</td></tr>"
            "<tr><td>084.2222B</td><td>101.0</td><td>1</td><td>2</td><td>3</td></tr>"
            "</table>"
        )
        types = applyhome.parse_pblanc_supply(html)
        self.assertEqual(len(types), 1)
        self.assertEqual(types[0].house_type, "084.2222B")


if __name__ == "__main__":
    unittest.main()
