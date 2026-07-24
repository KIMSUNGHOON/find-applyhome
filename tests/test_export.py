import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import server

UNITS = [
    {
        "dong": "101",
        "ho": "201",
        "status": "info",
        "fields": {
            "주택형": "084.9721A",
            "공급유형": "특별공급",
            "공고일": "2025.03.14",
            "당첨자 발표일": "2025.03.25",
            "계약체결일": "2025.04.07 ~ 2025.04.09",
            "입주예정": "2028.06",
            "전매제한": "1년",
            "분양금액(만원)": "99,000",
        },
    },
    {"dong": "101", "ho": "305", "status": "empty", "fields": {}},
    {"dong": "101", "ho": "402", "status": "error", "fields": {}},
]


class BuildCsvTest(unittest.TestCase):
    def test_엑셀용_BOM으로_시작한다(self):
        self.assertTrue(server.build_csv(UNITS).startswith("﻿"))

    def test_헤더가_명세대로다(self):
        header = server.build_csv(UNITS).lstrip("﻿").splitlines()[0]
        self.assertEqual(
            header,
            "동,호,타입,판정,주택형,공급유형,공고일,당첨자 발표일,계약체결일,입주예정,전매제한,분양금액(만원)",
        )

    def test_정보있음_행은_주택형에서_축약한_타입이_들어간다(self):
        lines = server.build_csv(UNITS).lstrip("﻿").strip().splitlines()
        self.assertEqual(lines[1].split(",")[2], "84A")

    def test_타입은_호와_판정_사이다(self):
        header = server.build_csv(UNITS).lstrip("﻿").splitlines()[0].split(",")
        self.assertEqual(header[1], "호")
        self.assertEqual(header[2], "타입")
        self.assertEqual(header[3], "판정")

    def test_세대수만큼_행이_나온다(self):
        lines = server.build_csv(UNITS).lstrip("﻿").strip().splitlines()
        self.assertEqual(len(lines), 4)  # 헤더 1 + 세대 3

    def test_판정을_한글로_적는다(self):
        lines = server.build_csv(UNITS).lstrip("﻿").strip().splitlines()
        self.assertIn("정보있음", lines[1])
        self.assertIn("정보없음", lines[2])
        self.assertIn("조회실패", lines[3])

    def test_정보없음_행은_타입만_있고_상세칸은_비어있다(self):
        lines = server.build_csv(UNITS).lstrip("﻿").strip().splitlines()
        self.assertEqual(lines[2], "101,305,,정보없음,,,,,,,,")

    def test_쉼표가_든_값은_따옴표로_감싼다(self):
        body = server.build_csv(UNITS)
        self.assertIn('"99,000"', body)


class UnitRetryApiTest(unittest.TestCase):
    """실패한 세대 하나를 다시 조회하는 엔드포인트."""

    @classmethod
    def setUpClass(cls):
        import threading
        import urllib.error
        import urllib.request
        from http.server import ThreadingHTTPServer

        import applyhome

        cls.urllib_error = urllib.error
        cls.urllib_request = urllib.request
        cls.original = applyhome.fetch_detail
        applyhome.fetch_detail = lambda hm, pb, dong_name, ho_no: applyhome.UnitDetail(
            dong_name, ho_no, "info", {"주택형": "084.9721"}
        )
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        import applyhome

        cls.httpd.shutdown()
        cls.httpd.server_close()
        applyhome.fetch_detail = cls.original

    def test_세대_하나를_다시_조회한다(self):
        import json

        url = f"http://127.0.0.1:{self.port}/api/unit?hm=1&pb=1&dong=101&ho=402"
        with self.urllib_request.urlopen(url, timeout=5) as response:
            body = json.loads(response.read().decode("utf-8"))
        self.assertEqual(body["status"], "info")
        self.assertEqual(body["dong"], "101")
        self.assertEqual(body["ho"], "402")
        self.assertEqual(body["fields"]["주택형"], "084.9721")

    def test_인자가_빠지면_400이다(self):
        url = f"http://127.0.0.1:{self.port}/api/unit?hm=1"
        with self.assertRaises(self.urllib_error.HTTPError) as caught:
            self.urllib_request.urlopen(url, timeout=5)
        self.assertEqual(caught.exception.code, 400)

    def test_토큰을_주면_보관된_스캔결과도_갱신된다(self):
        server.SCANS["tok"] = [
            {"dong": "101", "ho": "402", "status": "error", "fields": {}},
        ]
        url = f"http://127.0.0.1:{self.port}/api/unit?hm=1&pb=1&dong=101&ho=402&token=tok"
        with self.urllib_request.urlopen(url, timeout=5):
            pass
        self.assertEqual(server.SCANS["tok"][0]["status"], "info")
        self.assertEqual(server.SCANS["tok"][0]["fields"]["주택형"], "084.9721")


class ExportApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import threading
        import urllib.error
        import urllib.request
        from http.server import ThreadingHTTPServer

        cls.urllib_error = urllib.error
        cls.urllib_request = urllib.request
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def test_토큰으로_CSV를_받는다(self):
        server.SCANS["csvtok"] = UNITS
        url = f"http://127.0.0.1:{self.port}/api/export?token=csvtok"
        with self.urllib_request.urlopen(url, timeout=5) as response:
            body = response.read().decode("utf-8")
            self.assertIn("text/csv", response.headers["Content-Type"])
        self.assertTrue(body.startswith("﻿"))
        self.assertIn("정보없음", body)

    def test_없는_토큰은_404다(self):
        url = f"http://127.0.0.1:{self.port}/api/export?token=nope"
        with self.assertRaises(self.urllib_error.HTTPError) as caught:
            self.urllib_request.urlopen(url, timeout=5)
        self.assertEqual(caught.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
