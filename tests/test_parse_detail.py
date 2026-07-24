import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import applyhome

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


class ParseDetailInfoTest(unittest.TestCase):
    def setUp(self):
        html = (FIXTURES / "detail_info.html").read_text(encoding="utf-8")
        self.unit = applyhome.parse_detail(html, "1001", "201")

    def test_정보가_있으면_info로_판정한다(self):
        self.assertEqual(self.unit.status, "info")

    def test_동호는_인자로_받은_값을_유지한다(self):
        self.assertEqual(self.unit.dong, "1001")
        self.assertEqual(self.unit.ho, "201")

    def test_주요_필드값이_정확하다(self):
        fields = self.unit.fields
        self.assertEqual(fields["주택명"], "장위 푸르지오 마크원")
        self.assertEqual(fields["주택형"], "046.8700")
        self.assertEqual(fields["공고일"], "2026.06.19")
        self.assertEqual(fields["당첨자 발표일"], "2026.07.08")
        self.assertEqual(fields["계약체결일"], "2026.07.20 ~ 2026.07.23")
        self.assertEqual(fields["입주예정"], "2030.09")
        self.assertEqual(fields["공급유형"], "특별공급")
        self.assertEqual(fields["지역"], "서울")

    def test_각주가_붙은_라벨도_정규화된_키로_담긴다(self):
        fields = self.unit.fields
        self.assertEqual(fields["분양금액(만원)"], "83,430")
        self.assertEqual(fields["특이사항"], "투기과열지구, 청약과열지역, 정비사업, 과밀억제권역")
        self.assertEqual(fields["전매제한"], "3년(기간내 소유권이전등기시 해제)")

    def test_값이_빈_항목은_빈_문자열이_된다(self):
        self.assertEqual(self.unit.fields["추가입주 계약체결일"], "")

    def test_다음_라벨을_값으로_잘못_당겨오지_않는다(self):
        self.assertNotEqual(self.unit.fields["추가입주 계약체결일"], "입주예정")


class ParseDetailEmptyTest(unittest.TestCase):
    def test_정보가_없으면_empty로_판정한다(self):
        html = (FIXTURES / "detail_empty.html").read_text(encoding="utf-8")
        unit = applyhome.parse_detail(html, "101", "305")
        self.assertEqual(unit.status, "empty")
        self.assertEqual(unit.fields, {})

    def test_houseManageNo_태그가_아예_없어도_empty다(self):
        unit = applyhome.parse_detail("<html><body>오류</body></html>", "101", "305")
        self.assertEqual(unit.status, "empty")


class LabelOrderResilienceTest(unittest.TestCase):
    def test_행_순서가_바뀌어도_값이_정확히_매핑된다(self):
        html = """
        <div id="houseManageNo">2026000275</div>
        <table><tbody>
          <tr><td>공급유형</td><td>일반공급</td></tr>
          <tr><td>주택형</td><td>084.9721</td></tr>
          <tr><td>분양금액(만원)***</td><td>99,000</td></tr>
          <tr><td>주택명</td><td>테스트단지</td></tr>
        </tbody></table>
        """
        unit = applyhome.parse_detail(html, "101", "1502")
        self.assertEqual(unit.status, "info")
        self.assertEqual(unit.fields["공급유형"], "일반공급")
        self.assertEqual(unit.fields["주택형"], "084.9721")
        self.assertEqual(unit.fields["분양금액(만원)"], "99,000")
        self.assertEqual(unit.fields["주택명"], "테스트단지")


if __name__ == "__main__":
    unittest.main()
