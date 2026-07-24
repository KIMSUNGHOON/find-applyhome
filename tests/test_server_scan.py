import json
import pathlib
import sys
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import scanner
import server


def fake_scan(hm, pb, on_event, stop=None, **kwargs):
    on_event("meta", {"total": 2, "dongs": [{"name": "101", "hos": ["201", "202"], "grid": None}]})
    on_event("unit", {"dong": "101", "ho": "201", "status": "info", "fields": {"주택형": "084.9721"}})
    on_event("unit", {"dong": "101", "ho": "202", "status": "empty", "fields": {}})
    on_event("done", {"total": 2, "info": 1, "empty": 1, "error": 0, "elapsed": 0.2})


def parse_sse(text):
    events = []
    for block in text.strip().split("\n\n"):
        name = data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        if name:
            events.append((name, data))
    return events


class ScanStreamTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = scanner.scan_complex
        scanner.scan_complex = fake_scan
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        scanner.scan_complex = cls.original

    def stream(self):
        url = f"http://127.0.0.1:{self.port}/api/scan?hm=1&pb=1"
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.headers["Content-Type"], response.read().decode("utf-8")

    def test_이벤트스트림_컨텐트타입을_쓴다(self):
        content_type, _ = self.stream()
        self.assertIn("text/event-stream", content_type)

    def test_이벤트가_순서대로_흐른다(self):
        _, body = self.stream()
        names = [name for name, _ in parse_sse(body)]
        self.assertEqual(names, ["meta", "unit", "unit", "done"])

    def test_done에_토큰이_실린다(self):
        _, body = self.stream()
        done = parse_sse(body)[-1][1]
        self.assertIn("token", done)
        self.assertIn(done["token"], server.SCANS)

    def test_토큰으로_꺼낸_결과에_세대가_모두_들어있다(self):
        _, body = self.stream()
        token = parse_sse(body)[-1][1]["token"]
        self.assertEqual(len(server.SCANS[token]), 2)
        self.assertEqual(server.SCANS[token][1]["status"], "empty")

    def test_한글_필드가_깨지지_않는다(self):
        _, body = self.stream()
        units = [payload for name, payload in parse_sse(body) if name == "unit"]
        self.assertEqual(units[0]["fields"]["주택형"], "084.9721")


if __name__ == "__main__":
    unittest.main()
