import json
import pathlib
import sys
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api"))

import applyhome
import _lib
import server


class RoutingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = applyhome.search_complexes
        cls.original_cache = _lib.CACHE
        _lib.CACHE = None
        applyhome.search_complexes = lambda name="", area="", sigungu="", page=1: (
            [applyhome.Complex("2025000439", "2025000439", "상봉 센트럴 아이파크",
                               "2025.09.19", "2025.10.14", "일반공급 : 1년")],
            168,
        )
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        applyhome.search_complexes = cls.original
        _lib.CACHE = cls.original_cache

    def get(self, path):
        url = f"http://127.0.0.1:{self.port}{urllib.parse.quote(path, safe='/?=&%')}"
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, response.read()

    def test_검색_경로가_JSON을_돌려준다(self):
        status, raw = self.get("/api/search?name=상봉")
        self.assertEqual(status, 200)
        body = json.loads(raw.decode("utf-8"))
        self.assertEqual(body["total"], 168)
        self.assertEqual(body["complexes"][0]["name"], "상봉 센트럴 아이파크")

    def test_한글_검색어가_깨지지_않는다(self):
        status, raw = self.get("/api/search?name=%EC%83%81%EB%B4%89")
        self.assertEqual(status, 200)
        self.assertIn("상봉 센트럴 아이파크", raw.decode("utf-8"))

    def test_루트가_index_html을_준다(self):
        status, raw = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("청약홈 미계약 세대 스캐너", raw.decode("utf-8"))

    def test_cache_module을_javascript로_준다(self):
        url = f"http://127.0.0.1:{self.port}/cache.mjs"
        with urllib.request.urlopen(url, timeout=5) as response:
            self.assertEqual(response.headers.get_content_type(), "text/javascript")
            self.assertIn("selectUnitJobs", response.read().decode("utf-8"))

    def test_visits_module을_javascript로_준다(self):
        url = f"http://127.0.0.1:{self.port}/visits.mjs"
        with urllib.request.urlopen(url, timeout=5) as response:
            self.assertEqual(response.headers.get_content_type(), "text/javascript")
            self.assertIn("applyVisits", response.read().decode("utf-8"))

    def test_없는_경로는_404다(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.get("/api/nope")
        self.assertEqual(caught.exception.code, 404)

    def test_일곱_API_경로가_모두_연결되어_있다(self):
        self.assertEqual(
            set(_lib.ROUTES),
            {
                "/api/search",
                "/api/dongs",
                "/api/hos",
                "/api/unit",
                "/api/pblanc",
                "/api/cache",
                "/api/visits",
            },
        )

    def test_cache_미설정은_disabled_JSON이다(self):
        status, raw = self.get("/api/cache?hm=1&pb=2")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["cache"], "disabled")


if __name__ == "__main__":
    unittest.main()
