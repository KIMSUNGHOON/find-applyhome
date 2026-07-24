"""로컬 실행용 HTTP 서버.

브라우저에서 청약홈을 직접 부르면 CORS 에 막히므로 이 서버가 대신 호출한다.
엔드포인트 로직은 api/_lib.py 에 있고, Vercel 배포본과 같은 코드를 탄다.
127.0.0.1 에만 바인딩하며 외부에 열지 않는다.
"""

from __future__ import annotations

import pathlib
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "api"))

import _lib

PUBLIC_DIR = pathlib.Path(__file__).resolve().parent / "public"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # 요청 로그를 조용히 만든다
        pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path in ("/", "/index.html"):
            self._send_file(PUBLIC_DIR / "index.html", "text/html; charset=utf-8")
            return

        if parsed.path == "/cache.mjs":
            self._send_file(PUBLIC_DIR / "cache.mjs", "text/javascript; charset=utf-8")
            return

        route = _lib.ROUTES.get(parsed.path)
        if route is None:
            _lib.respond(self, 404, {"message": "없는 경로입니다."})
            return

        query = urllib.parse.parse_qs(parsed.query)
        _lib.respond(self, *route(query))

    def _send_file(self, path: pathlib.Path, content_type: str):
        if not path.exists():
            _lib.respond(self, 404, {"message": "파일이 없습니다."})
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
