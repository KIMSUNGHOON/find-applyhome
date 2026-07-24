import json
import pathlib
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import applyhome
import server


class SearchApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = applyhome.search_complexes
        cls.received = {}

        def fake_search(name="", area="", sigungu="", page=1):
            cls.received.clear()
            cls.received.update(name=name, area=area, sigungu=sigungu, page=page)
            return (
                [
                    applyhome.Complex(
                        house_manage_no="2025000439",
                        pblanc_no="2025000439",
                        name="상봉 센트럴 아이파크",
                        notice_date="2025.03.14",
                        winner_date="2025.03.25",
                        resale_limit="일반공급 : 1년",
                    )
                ],
                168,
            )

        applyhome.search_complexes = fake_search
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        applyhome.search_complexes = cls.original

    def get(self, path):
        # 브라우저가 하는 것처럼 한글을 percent-encoding 한다
        url = f"http://127.0.0.1:{self.port}{urllib.parse.quote(path, safe='/?=&%')}"
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_검색결과를_JSON으로_돌려준다(self):
        status, body = self.get("/api/search?name=상봉")
        self.assertEqual(status, 200)
        self.assertEqual(body["total"], 168)
        self.assertEqual(len(body["complexes"]), 1)

    def test_단지_필드가_그대로_전달된다(self):
        _, body = self.get("/api/search?name=상봉")
        first = body["complexes"][0]
        self.assertEqual(first["name"], "상봉 센트럴 아이파크")
        self.assertEqual(first["house_manage_no"], "2025000439")
        self.assertEqual(first["pblanc_no"], "2025000439")
        self.assertEqual(first["notice_date"], "2025.03.14")

    def test_한글_검색어가_서버까지_온전히_전달된다(self):
        status, _ = self.get("/api/search?name=%EC%83%81%EB%B4%89")
        self.assertEqual(status, 200)
        self.assertEqual(self.received["name"], "상봉")

    def test_지역과_페이지_인자가_전달된다(self):
        self.get("/api/search?name=&area=서울&sigungu=중랑구&page=3")
        self.assertEqual(self.received["area"], "서울")
        self.assertEqual(self.received["sigungu"], "중랑구")
        self.assertEqual(self.received["page"], 3)

    def test_페이지가_숫자가_아니면_1로_떨어진다(self):
        self.get("/api/search?name=상봉&page=abc")
        self.assertEqual(self.received["page"], 1)

    def test_없는_경로는_404다(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.get("/api/nope")
        self.assertEqual(caught.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
