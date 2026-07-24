"""로컬 HTTP 서버. 브라우저와 청약홈 사이를 중개한다.

브라우저에서 청약홈을 직접 부르면 CORS 에 막히므로 이 서버가 대신 호출한다.
127.0.0.1 에만 바인딩하며 외부에 열지 않는다.
"""

from __future__ import annotations

import csv
import io
import json
import pathlib
import secrets
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import applyhome
import grid
import scanner

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


CSV_HEADER = (
    "동", "호", "타입", "판정", "주택형", "공급유형", "공고일",
    "당첨자 발표일", "계약체결일", "입주예정", "전매제한", "분양금액(만원)",
)
STATUS_LABEL = {"info": "정보있음", "empty": "정보없음", "error": "조회실패"}


def build_csv(units: list[dict]) -> str:
    """엑셀에서 바로 열리도록 UTF-8 BOM을 붙인 CSV 를 만든다.

    '타입' 은 주택형을 축약한 값이다. 정보없음 세대는 청약홈이 주택형을 주지 않으므로 빈칸이 된다.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_HEADER)
    for unit in units:
        fields = unit.get("fields") or {}
        house_type = fields.get("주택형", "")
        writer.writerow(
            [
                unit.get("dong", ""),
                unit.get("ho", ""),
                grid.short_type(house_type) if house_type else "",
                STATUS_LABEL.get(unit.get("status", ""), unit.get("status", "")),
                *(fields.get(key, "") for key in CSV_HEADER[4:]),
            ]
        )
    return "﻿" + buffer.getvalue()


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
        elif parsed.path == "/api/scan":
            self._handle_scan(query)
        elif parsed.path == "/api/export":
            self._handle_export(query)
        elif parsed.path == "/api/unit":
            self._handle_unit(query)
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

    def _handle_scan(self, query: dict):
        hm = self._one(query, "hm")
        pb = self._one(query, "pb")
        if not hm or not pb:
            self._send_json({"message": "hm, pb 값이 필요합니다."}, status=400)
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        stop = threading.Event()
        collected: list[dict] = []

        def emit(name: str, payload: dict):
            if name == "unit":
                collected.append(payload)
            if name == "done":
                token = secrets.token_hex(8)
                SCANS.clear()          # 마지막 스캔 하나만 남긴다
                SCANS[token] = collected
                payload = {**payload, "token": token}
            try:
                chunk = f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                self.wfile.write(chunk.encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                stop.set()             # 브라우저가 떠났다

        scanner.scan_complex(hm, pb, emit, stop=stop)
        self.close_connection = True

    def _handle_export(self, query: dict):
        token = self._one(query, "token")
        units = SCANS.get(token)
        if units is None:
            self._send_json({"message": "스캔 결과를 찾을 수 없습니다."}, status=404)
            return
        body = build_csv(units).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", 'attachment; filename="scan.csv"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_unit(self, query: dict):
        """조회에 실패한 세대 하나를 다시 부른다.

        token 이 함께 오면 보관 중인 스캔 결과도 갱신한다. 그래야 이어서 받는 CSV 에
        재시도 결과가 반영된다.
        """
        hm = self._one(query, "hm")
        pb = self._one(query, "pb")
        dong = self._one(query, "dong")
        ho = self._one(query, "ho")
        if not (hm and pb and dong and ho):
            self._send_json({"message": "hm, pb, dong, ho 값이 모두 필요합니다."}, status=400)
            return

        try:
            unit = applyhome.fetch_detail(hm, pb, dong, ho)
            payload = {
                "dong": unit.dong, "ho": unit.ho,
                "status": unit.status, "fields": unit.fields,
            }
        except applyhome.ApplyhomeError as error:
            payload = {
                "dong": dong, "ho": ho, "status": "error",
                "fields": {}, "message": str(error),
            }

        units = SCANS.get(self._one(query, "token"))
        if units is not None:
            for index, existing in enumerate(units):
                if existing.get("dong") == dong and existing.get("ho") == ho:
                    units[index] = payload
                    break

        self._send_json(payload)

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
