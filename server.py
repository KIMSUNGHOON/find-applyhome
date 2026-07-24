"""로컬 HTTP 서버. 브라우저와 청약홈 사이를 중개한다.

브라우저에서 청약홈을 직접 부르면 CORS 에 막히므로 이 서버가 대신 호출한다.
127.0.0.1 에만 바인딩하며 외부에 열지 않는다.
"""

from __future__ import annotations

import json
import pathlib
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import applyhome

STATIC_DIR = pathlib.Path(__file__).resolve().parent / "static"

# 마지막 스캔 결과만 보관한다. {token: [unit, ...]}
SCANS: dict[str, list[dict]] = {}


def complex_to_dict(item: applyhome.Complex) -> dict:
    return {
        "house_manage_no": item.house_manage_no,
        "pblanc_no": item.pblanc_no,
        "name": item.name,
        "notice_date": item.notice_date,
        "winner_date": item.winner_date,
        "resale_limit": item.resale_limit,
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # 요청 로그를 조용히 만든다
        pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)

        if parsed.path in ("/", "/index.html"):
            self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
        elif parsed.path == "/api/search":
            self._handle_search(query)
        else:
            self._send_json({"message": "없는 경로입니다."}, status=404)

    def _one(self, query: dict, key: str, default: str = "") -> str:
        return query.get(key, [default])[0]

    def _handle_search(self, query: dict):
        try:
            page = int(self._one(query, "page", "1"))
        except ValueError:
            page = 1
        try:
            complexes, total = applyhome.search_complexes(
                name=self._one(query, "name"),
                area=self._one(query, "area"),
                sigungu=self._one(query, "sigungu"),
                page=page,
            )
        except applyhome.ApplyhomeError as error:
            self._send_json({"message": str(error)}, status=502)
            return
        self._send_json(
            {"complexes": [complex_to_dict(c) for c in complexes], "total": total}
        )

    def _send_json(self, payload: dict, status: int = 200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: pathlib.Path, content_type: str):
        if not path.exists():
            self._send_json({"message": "파일이 없습니다."}, status=404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(port: int = 8765) -> None:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"http://127.0.0.1:{port} 에서 실행 중입니다. 종료하려면 Ctrl+C.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n종료합니다.")
    finally:
        httpd.server_close()
