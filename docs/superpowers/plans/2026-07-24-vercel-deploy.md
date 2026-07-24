# Vercel 배포 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 비개발자가 브라우저에서 URL 만 열면 쓸 수 있도록 Vercel 서버리스로 배포한다. 로컬 실행(`python3 app.py`)도 그대로 유지한다.

**Architecture:** 엔드포인트 로직을 `api/_lib.py` 의 순수 함수로 모으고, Vercel 진입점(`api/*.py`)과 로컬 서버(`server.py`)가 그것을 얇게 감싼다. 서버리스는 긴 연결과 전역 상태를 쓸 수 없으므로 SSE 스캔 루프와 서버측 CSV 생성을 브라우저로 옮긴다.

**Tech Stack:** Python 3 표준 라이브러리만, 바닐라 JS. Vercel Python 런타임.

선행 스펙: `docs/superpowers/specs/2026-07-24-vercel-deploy-design.md`

## Global Constraints

- **서드파티 패키지 금지.** 표준 라이브러리만 쓴다. `requirements.txt` 를 만들지 않는다.
- **`applyhome.py` 와 `grid.py` 는 수정하지 않는다.** 이 프로젝트의 핵심 파싱 자산이며 테스트 47건이 이를 검증한다.
- **로컬과 배포본이 같은 코드를 탄다.** `server.py` 와 `api/*.py` 가 모두 `api/_lib.py` 를 호출한다. 로직을 복제하지 않는다.
- **프론트엔드는 한 파일이다.** `public/index.html` 을 로컬 서버도 그대로 서빙한다.
- Vercel 규약: `api/` 안의 `.py` 는 `BaseHTTPRequestHandler` 를 상속한 **`handler`** 클래스를 정의해야 하고, **`_` 로 시작하는 파일은 함수로 변환되지 않는다.**
- 청약홈 호출 규약은 그대로다 — 브라우저에서 **동시 4개, 요청 간 0.1초**.
- `/api/unit` 만 개별 실패 시 `200` 과 `{"status": "error"}` 를 반환한다. 나머지는 실패 시 `502`.

## File Structure

| 파일 | 책임 |
|---|---|
| `api/_lib.py` | 엔드포인트 로직 5종을 순수 함수로. `(status, payload)` 반환 |
| `api/search.py` `api/dongs.py` `api/hos.py` `api/unit.py` `api/pblanc.py` | Vercel 진입점. 각 5줄 내외 |
| `server.py` | 로컬 실행용 라우팅 + 정적 파일 서빙 |
| `public/index.html` | UI 전체 (`static/` 에서 이동) |
| `vercel.json` | 함수 번들 설정 |
| `tests/test_api.py` | `_lib` 함수 직접 테스트 |
| `applyhome.py` `grid.py` `app.py` | 변경 없음 (`app.py` 는 그대로 `server.serve` 호출) |
| `scanner.py` | **삭제** |

---

### Task 1: `api/_lib.py` — 엔드포인트 로직

**Files:**
- Create: `api/_lib.py`
- Create: `tests/test_api.py`

**Interfaces:**
- Consumes: `applyhome.search_complexes` / `list_dongs` / `list_hos` / `fetch_detail` / `fetch_pblanc_supply` / `Complex` / `ApplyhomeError`, `grid.build_grid` / `short_type` / `net_area`
- Produces: `search(q) -> (int, dict)`, `dongs(q) -> (int, dict)`, `hos(q) -> (int, dict)`, `unit(q) -> (int, dict)`, `pblanc(q) -> (int, dict)`. 모두 `q` 는 `urllib.parse.parse_qs` 결과(`dict[str, list[str]]`). 그 외 `one(q, key, default="") -> str`, `ROUTES: dict[str, callable]`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_api.py`:

```python
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api"))

import applyhome
import _lib

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def q(**kwargs):
    """parse_qs 형태로 만든다 — 값이 리스트다."""
    return {k: [v] for k, v in kwargs.items()}


class OneTest(unittest.TestCase):
    def test_첫_값을_꺼낸다(self):
        self.assertEqual(_lib.one(q(name="상봉"), "name"), "상봉")

    def test_없으면_기본값이다(self):
        self.assertEqual(_lib.one({}, "name"), "")
        self.assertEqual(_lib.one({}, "page", "1"), "1")


class SearchTest(unittest.TestCase):
    def setUp(self):
        self.original = applyhome.search_complexes
        self.received = {}

        def fake(name="", area="", sigungu="", page=1):
            self.received.update(name=name, area=area, sigungu=sigungu, page=page)
            return ([applyhome.Complex("2025000439", "2025000439", "상봉 센트럴 아이파크",
                                       "2025.09.19", "2025.10.14", "일반공급 : 1년")], 168)

        applyhome.search_complexes = fake

    def tearDown(self):
        applyhome.search_complexes = self.original

    def test_검색_결과를_돌려준다(self):
        status, body = _lib.search(q(name="상봉"))
        self.assertEqual(status, 200)
        self.assertEqual(body["total"], 168)
        self.assertEqual(body["complexes"][0]["name"], "상봉 센트럴 아이파크")
        self.assertEqual(body["complexes"][0]["house_manage_no"], "2025000439")

    def test_인자가_그대로_전달된다(self):
        _lib.search(q(name="상봉", area="서울", sigungu="중랑구", page="3"))
        self.assertEqual(self.received["area"], "서울")
        self.assertEqual(self.received["page"], 3)

    def test_페이지가_숫자가_아니면_1이다(self):
        _lib.search(q(name="상봉", page="abc"))
        self.assertEqual(self.received["page"], 1)

    def test_청약홈_실패는_502다(self):
        applyhome.search_complexes = lambda **kw: (_ for _ in ()).throw(
            applyhome.ApplyhomeError("연결 실패"))
        status, body = _lib.search(q(name="상봉"))
        self.assertEqual(status, 502)
        self.assertIn("message", body)


class DongsTest(unittest.TestCase):
    def setUp(self):
        self.original = applyhome.list_dongs

    def tearDown(self):
        applyhome.list_dongs = self.original

    def test_동_목록을_sn과_name으로_돌려준다(self):
        applyhome.list_dongs = lambda hm, pb: [applyhome.Dong(1, "101"), applyhome.Dong(2, "102")]
        status, body = _lib.dongs(q(hm="1", pb="1"))
        self.assertEqual(status, 200)
        self.assertEqual(body["dongs"], [{"sn": 1, "name": "101"}, {"sn": 2, "name": "102"}])

    def test_동이_없으면_빈_배열이다(self):
        applyhome.list_dongs = lambda hm, pb: []
        status, body = _lib.dongs(q(hm="1", pb="1"))
        self.assertEqual(status, 200)
        self.assertEqual(body["dongs"], [])

    def test_인자가_빠지면_400이다(self):
        status, _ = _lib.dongs(q(hm="1"))
        self.assertEqual(status, 400)

    def test_대기열이면_502다(self):
        applyhome.list_dongs = lambda hm, pb: (_ for _ in ()).throw(
            applyhome.BlockedError("대기열입니다"))
        status, body = _lib.dongs(q(hm="1", pb="1"))
        self.assertEqual(status, 502)
        self.assertIn("대기열", body["message"])


class HosTest(unittest.TestCase):
    def setUp(self):
        self.original = applyhome.list_hos

    def tearDown(self):
        applyhome.list_hos = self.original

    def test_호_목록과_격자를_돌려준다(self):
        applyhome.list_hos = lambda hm, pb, sn: [
            applyhome.Ho(1, "201"), applyhome.Ho(2, "305"), applyhome.Ho(3, "1105")]
        status, body = _lib.hos(q(hm="1", pb="1", sn="1"))
        self.assertEqual(status, 200)
        self.assertEqual(body["hos"], ["201", "305", "1105"])
        self.assertEqual(body["grid"]["cells"]["1105"], [11, "05"])

    def test_격자화가_안_되면_grid가_None이다(self):
        applyhome.list_hos = lambda hm, pb, sn: [applyhome.Ho(1, "1"), applyhome.Ho(2, "A2")]
        _, body = _lib.hos(q(hm="1", pb="1", sn="1"))
        self.assertIsNone(body["grid"])

    def test_sn이_숫자가_아니면_400이다(self):
        status, _ = _lib.hos(q(hm="1", pb="1", sn="abc"))
        self.assertEqual(status, 400)


class UnitTest(unittest.TestCase):
    def setUp(self):
        self.original = applyhome.fetch_detail

    def tearDown(self):
        applyhome.fetch_detail = self.original

    def test_세대_정보를_돌려준다(self):
        applyhome.fetch_detail = lambda hm, pb, d, h: applyhome.UnitDetail(
            d, h, "info", {"주택형": "084.8422A"})
        status, body = _lib.unit(q(hm="1", pb="1", dong="101", ho="201"))
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "info")
        self.assertEqual(body["fields"]["주택형"], "084.8422A")

    def test_실패해도_200에_error_상태다(self):
        # 개별 세대 실패가 스캔 전체를 멈추면 안 된다
        applyhome.fetch_detail = lambda hm, pb, d, h: (_ for _ in ()).throw(
            applyhome.ApplyhomeError("타임아웃"))
        status, body = _lib.unit(q(hm="1", pb="1", dong="101", ho="201"))
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "error")
        self.assertEqual(body["dong"], "101")
        self.assertEqual(body["ho"], "201")

    def test_인자가_빠지면_400이다(self):
        status, _ = _lib.unit(q(hm="1", pb="1", dong="101"))
        self.assertEqual(status, 400)


class PblancTest(unittest.TestCase):
    def setUp(self):
        self.original = applyhome.fetch_pblanc_supply

    def tearDown(self):
        applyhome.fetch_pblanc_supply = self.original

    def test_공고_정보에_축약과_전용면적이_붙는다(self):
        applyhome.fetch_pblanc_supply = lambda hm, pb: [
            applyhome.SupplyType("084.8422A", "116.9496", 22, 23, 45)]
        status, body = _lib.pblanc(q(hm="1", pb="1"))
        self.assertEqual(status, 200)
        s = body["supply"][0]
        self.assertEqual(s["type"], "084.8422A")
        self.assertEqual(s["short"], "84A")
        self.assertEqual(s["net_area"], "84.8422")
        self.assertEqual((s["general"], s["special"], s["total"]), (22, 23, 45))

    def test_공고가_없으면_supply가_None이다(self):
        applyhome.fetch_pblanc_supply = lambda hm, pb: []
        _, body = _lib.pblanc(q(hm="1", pb="1"))
        self.assertIsNone(body["supply"])

    def test_조회가_터져도_supply가_None이고_200이다(self):
        # 공고는 부가 정보다. 실패해도 스캔을 막지 않는다
        applyhome.fetch_pblanc_supply = lambda hm, pb: (_ for _ in ()).throw(RuntimeError("오류"))
        status, body = _lib.pblanc(q(hm="1", pb="1"))
        self.assertEqual(status, 200)
        self.assertIsNone(body["supply"])


class RoutesTest(unittest.TestCase):
    def test_다섯_경로가_등록되어_있다(self):
        self.assertEqual(
            set(_lib.ROUTES),
            {"/api/search", "/api/dongs", "/api/hos", "/api/unit", "/api/pblanc"},
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 테스트를 돌려 실패를 확인한다**

Run: `python3 -m unittest tests.test_api -v`
Expected: FAIL — `ModuleNotFoundError: No module named '_lib'`

- [ ] **Step 3: `api/_lib.py` 구현**

```python
"""엔드포인트 로직. Vercel 함수와 로컬 서버가 함께 쓴다.

각 함수는 parse_qs 결과를 받아 (HTTP 상태, JSON 페이로드) 를 돌려준다.
HTTP 를 직접 다루지 않으므로 서버를 띄우지 않고 테스트할 수 있다.

`_` 로 시작하는 파일이라 Vercel 이 함수로 변환하지 않는다.
"""

from __future__ import annotations

import pathlib
import sys

# applyhome.py / grid.py 는 저장소 루트에 있다. 로컬과 Vercel 양쪽에서 import 되어야 한다.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import applyhome
import grid


def one(query: dict, key: str, default: str = "") -> str:
    """parse_qs 결과에서 첫 값을 꺼낸다."""
    values = query.get(key)
    return values[0] if values else default


def _complex_to_dict(item: applyhome.Complex) -> dict:
    return {
        "house_manage_no": item.house_manage_no,
        "pblanc_no": item.pblanc_no,
        "name": item.name,
        "notice_date": item.notice_date,
        "winner_date": item.winner_date,
        "resale_limit": item.resale_limit,
    }


def search(query: dict) -> tuple[int, dict]:
    try:
        page = int(one(query, "page", "1"))
    except ValueError:
        page = 1
    try:
        complexes, total = applyhome.search_complexes(
            name=one(query, "name"),
            area=one(query, "area"),
            sigungu=one(query, "sigungu"),
            page=page,
        )
    except applyhome.ApplyhomeError as error:
        return 502, {"message": str(error)}
    return 200, {"complexes": [_complex_to_dict(c) for c in complexes], "total": total}


def dongs(query: dict) -> tuple[int, dict]:
    hm, pb = one(query, "hm"), one(query, "pb")
    if not (hm and pb):
        return 400, {"message": "hm, pb 값이 필요합니다."}
    try:
        found = applyhome.list_dongs(hm, pb)
    except applyhome.ApplyhomeError as error:
        return 502, {"message": str(error)}
    return 200, {"dongs": [{"sn": d.sn, "name": d.name} for d in found]}


def hos(query: dict) -> tuple[int, dict]:
    hm, pb = one(query, "hm"), one(query, "pb")
    if not (hm and pb):
        return 400, {"message": "hm, pb 값이 필요합니다."}
    try:
        sn = int(one(query, "sn"))
    except ValueError:
        return 400, {"message": "sn 값이 필요합니다."}
    try:
        found = applyhome.list_hos(hm, pb, sn)
    except applyhome.ApplyhomeError as error:
        return 502, {"message": str(error)}
    numbers = [h.no for h in found]
    return 200, {"hos": numbers, "grid": grid.build_grid(numbers)}


def unit(query: dict) -> tuple[int, dict]:
    """세대 1건. 개별 실패가 스캔을 멈추면 안 되므로 실패해도 200 을 돌려준다."""
    hm, pb = one(query, "hm"), one(query, "pb")
    dong, ho = one(query, "dong"), one(query, "ho")
    if not (hm and pb and dong and ho):
        return 400, {"message": "hm, pb, dong, ho 값이 모두 필요합니다."}
    try:
        found = applyhome.fetch_detail(hm, pb, dong, ho)
    except applyhome.ApplyhomeError as error:
        return 200, {"dong": dong, "ho": ho, "status": "error", "fields": {},
                     "message": str(error)}
    return 200, {"dong": found.dong, "ho": found.ho,
                 "status": found.status, "fields": found.fields}


def pblanc(query: dict) -> tuple[int, dict]:
    """공고 타입별 공급세대수. 부가 정보이므로 어떤 실패든 supply=None 으로 넘긴다."""
    hm, pb = one(query, "hm"), one(query, "pb")
    if not (hm and pb):
        return 400, {"message": "hm, pb 값이 필요합니다."}
    try:
        types = applyhome.fetch_pblanc_supply(hm, pb)
    except Exception:
        return 200, {"supply": None}
    if not types:
        return 200, {"supply": None}
    return 200, {
        "supply": [
            {
                "type": t.house_type,
                "short": grid.short_type(t.house_type),
                "net_area": grid.net_area(t.house_type),
                "area": t.area,
                "general": t.general,
                "special": t.special,
                "total": t.total,
            }
            for t in types
        ]
    }


ROUTES = {
    "/api/search": search,
    "/api/dongs": dongs,
    "/api/hos": hos,
    "/api/unit": unit,
    "/api/pblanc": pblanc,
}
```

- [ ] **Step 4: 테스트를 돌려 통과를 확인한다**

Run: `python3 -m unittest tests.test_api -v`
Expected: PASS — 20개 테스트 전부 ok
(One 2 + Search 4 + Dongs 4 + Hos 3 + Unit 3 + Pblanc 3 + Routes 1)

- [ ] **Step 5: 커밋**

```bash
git add api/_lib.py tests/test_api.py
git commit -m "feat: 엔드포인트 로직을 순수 함수로 분리"
```

---

### Task 2: Vercel 진입점과 로컬 서버

**Files:**
- Create: `api/search.py`, `api/dongs.py`, `api/hos.py`, `api/unit.py`, `api/pblanc.py`
- Rewrite: `server.py`
- Modify: `tests/test_server_search.py`
- Delete: `tests/test_server_scan.py`, `tests/test_export.py`

**Interfaces:**
- Consumes: Task 1 의 `_lib.ROUTES`, `_lib.search` 등
- Produces: `server.Handler` (로컬 라우팅), `server.serve(port=8765)`, `server.PUBLIC_DIR`

- [ ] **Step 1: `api/_lib.py` 에 `respond` 를 먼저 추가한다**

다음 스텝의 진입점 5개가 모두 이 함수를 쓴다. 파일 상단 import 에 `import json` 을 넣고,
`one` 함수 바로 위에 추가한다:

```python
def respond(request, status: int, payload: dict) -> None:
    """BaseHTTPRequestHandler 에 JSON 을 써 보낸다. Vercel 과 로컬이 함께 쓴다."""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request.send_response(status)
    request.send_header("Content-Type", "application/json; charset=utf-8")
    request.send_header("Content-Length", str(len(body)))
    request.end_headers()
    request.wfile.write(body)
```

- [ ] **Step 2: Vercel 진입점 5개를 만든다**

다섯 파일이 같은 모양이다. `api/search.py`:

```python
"""Vercel 진입점. 로직은 _lib 에 있다."""

import pathlib
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import _lib


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _lib.respond(self, *_lib.search(query))
```

`api/dongs.py` — 마지막 줄만 다르다:

```python
"""Vercel 진입점. 로직은 _lib 에 있다."""

import pathlib
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import _lib


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _lib.respond(self, *_lib.dongs(query))
```

`api/hos.py`:

```python
"""Vercel 진입점. 로직은 _lib 에 있다."""

import pathlib
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import _lib


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _lib.respond(self, *_lib.hos(query))
```

`api/unit.py`:

```python
"""Vercel 진입점. 로직은 _lib 에 있다."""

import pathlib
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import _lib


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _lib.respond(self, *_lib.unit(query))
```

`api/pblanc.py`:

```python
"""Vercel 진입점. 로직은 _lib 에 있다."""

import pathlib
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import _lib


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _lib.respond(self, *_lib.pblanc(query))
```

- [ ] **Step 3: `server.py` 를 통째로 교체한다**

```python
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
```

- [ ] **Step 4: 못 쓰게 된 테스트를 지운다**

`test_server_scan.py` 는 SSE 를, `test_export.py` 는 서버측 CSV 를 검증한다. 둘 다 사라졌다.

```bash
git rm tests/test_server_scan.py tests/test_export.py
```

- [ ] **Step 5: `tests/test_server_search.py` 를 로컬 라우팅 테스트로 고친다**

파일 전체를 아래로 교체한다. `_lib` 단위 테스트는 Task 1 에 있으므로, 여기서는 **라우팅과 정적 파일 서빙만** 확인한다:

```python
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
import server


class RoutingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = applyhome.search_complexes
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

    def test_없는_경로는_404다(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.get("/api/nope")
        self.assertEqual(caught.exception.code, 404)

    def test_다섯_API_경로가_모두_연결되어_있다(self):
        import _lib
        for path in _lib.ROUTES:
            self.assertIn(path, _lib.ROUTES)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 6: `static/` 을 `public/` 으로 옮긴다**

Vercel 은 `public/` 을 정적 디렉토리로 자동 서빙한다.

```bash
git mv static public
```

- [ ] **Step 7: 테스트를 돌린다**

`test_scanner.py` 가 아직 남아 있어 `discover` 는 실패한다 (Task 4 에서 지운다).
지금은 이번 Task 의 대상만 확인한다:

Run: `python3 -m unittest tests.test_api tests.test_server_search -v`
Expected: PASS — 25개 전부 ok (test_api 20 + test_server_search 5)

- [ ] **Step 8: 커밋**

```bash
git add api server.py tests public
git commit -m "feat: Vercel 진입점과 로컬 라우팅을 _lib 위로 통합"
```

---

### Task 3: 브라우저 스캔 루프와 CSV

**Files:**
- Modify: `public/index.html` (`<script>` 안의 스캔·CSV 부분)

**Interfaces:**
- Consumes: Task 1·2 의 `/api/dongs`, `/api/hos`, `/api/unit`, `/api/pblanc`
- Produces: 없음 (최종 화면). 기존 함수 `onMeta` / `onUnit` / `onDone` / `renderSummary` / `renderEmptyList` / `renderLegend` / `showDetail` 은 시그니처 그대로 재사용한다

- [ ] **Step 1: 스캔 관련 코드를 새 루프로 교체한다**

`el("scan-button").addEventListener("click", ...)` 블록 전체부터 `finishScan` 함수 끝까지를 아래로 교체한다.
`EventSource` 를 쓰지 않고 개별 요청을 동시 4개로 돌린다:

```javascript
const CONCURRENCY = 4;
const REQUEST_GAP_MS = 100;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// 작업 목록을 동시 CONCURRENCY 개로 처리한다. 동·호 목록 조회와 세대 조회가 같은 러너를 쓴다.
// 청약홈이 공공 사이트라 워커마다 요청 사이에 REQUEST_GAP_MS 를 둔다.
async function runPool(items, worker) {
  const results = new Array(items.length);
  let next = 0;
  async function loop() {
    while (true) {
      const index = next++;
      if (index >= items.length || state.aborted) return;
      await sleep(REQUEST_GAP_MS);
      if (state.aborted) return;
      results[index] = await worker(items[index], index);
    }
  }
  await Promise.all(Array.from({ length: CONCURRENCY }, loop));
  return results;
}

async function getJson(path, params) {
  const response = await fetch(path + "?" + new URLSearchParams(params));
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.message || `요청 실패 (${response.status})`);
  return body;
}

el("scan-button").addEventListener("click", async () => {
  if (!state.complex) return;
  state.meta = null;
  state.units = new Map();
  state.aborted = false;
  el("grids").innerHTML = "";
  el("summary").innerHTML = "";
  el("empty-list").innerHTML = "";
  el("detail").innerHTML = "";
  el("notice-band").classList.add("hide");
  el("scan-button").disabled = true;
  el("stop-button").classList.remove("hide");
  el("progress").textContent = "동·호 목록을 불러오는 중…";

  const hm = state.complex.house_manage_no;
  const pb = state.complex.pblanc_no;
  const started = Date.now();

  try {
    const { dongs } = await getJson("/api/dongs", { hm, pb });
    if (!dongs.length) {
      el("progress").textContent = "이 단지는 아직 분양권 정보가 등록되지 않았습니다.";
      finishScan();
      return;
    }

    // 동마다 호 목록을 받는다
    const perDong = await runPool(dongs, (dong) =>
      getJson("/api/hos", { hm, pb, sn: dong.sn }).then((r) => ({ ...r, name: dong.name }))
    );
    if (state.aborted) { finishScan(); return; }

    const metaDongs = perDong.filter(Boolean).map((d) => ({
      name: d.name, hos: d.hos, grid: d.grid,
    }));
    const jobs = [];
    metaDongs.forEach((d) => d.hos.forEach((ho) => jobs.push({ dong: d.name, ho })));

    if (!jobs.length) {
      el("progress").textContent = "이 단지는 아직 분양권 정보가 등록되지 않았습니다.";
      finishScan();
      return;
    }

    // 공고 정보는 부가 정보다. 실패해도 스캔을 막지 않는다.
    const supply = await getJson("/api/pblanc", { hm, pb })
      .then((r) => r.supply)
      .catch(() => null);

    state.meta = { total: jobs.length, dongs: metaDongs, supply };
    onMeta(state.meta);
    el("progress").textContent = `0 / ${jobs.length}`;

    await runPool(jobs, async (job) => {
      const unit = await getJson("/api/unit", { hm, pb, dong: job.dong, ho: job.ho })
        .catch(() => ({ dong: job.dong, ho: job.ho, status: "error", fields: {} }));
      state.units.set(unit.dong + "-" + unit.ho, unit);
      onUnit(unit);
      el("progress").textContent = `${state.units.size} / ${jobs.length}`;
      return unit;
    });

    if (state.aborted) {
      el("progress").textContent = `중단됨 · ${state.units.size}세대까지 조회`;
      finishScan();
      return;
    }

    const tally = { info: 0, empty: 0, error: 0 };
    state.units.forEach((u) => { tally[u.status] = (tally[u.status] || 0) + 1; });
    const summary = {
      total: jobs.length, ...tally,
      elapsed: ((Date.now() - started) / 1000).toFixed(1),
    };
    el("progress").textContent =
      `완료 · ${summary.total}세대 중 정보없음 ${summary.empty}건` +
      (summary.error ? ` · 실패 ${summary.error}건` : "") +
      ` (${summary.elapsed}초)`;
    finishScan();
    onDone(summary);
  } catch (error) {
    el("progress").textContent = error.message;
    finishScan();
  }
});

el("stop-button").addEventListener("click", () => {
  state.aborted = true;
  el("progress").textContent = `중단하는 중… (${state.units.size}세대까지 조회)`;
});

function finishScan() {
  el("scan-button").disabled = false;
  el("stop-button").classList.add("hide");
}
```

- [ ] **Step 2: `state` 에 `aborted` 를 넣고 `source` 를 뺀다**

`const state = {...}` 선언에서 `source: null` 을 지우고 `aborted: false` 를 넣는다:

```javascript
const state = {
  complex: null, meta: null, units: new Map(), aborted: false,
  search: { name: "", area: "", page: 1, loaded: 0, total: 0 },
};
```

`state.token` 도 더는 쓰지 않으므로 넣지 않는다. CSV 를 브라우저가 만든다.

- [ ] **Step 3: CSV 를 브라우저에서 만든다**

`renderActions` 를 아래로 교체한다:

```javascript
const CSV_HEADER = [
  "동", "호", "타입", "판정", "주택형", "공급유형", "공고일",
  "당첨자 발표일", "계약체결일", "입주예정", "전매제한", "분양금액(만원)",
];
const STATUS_LABEL = { info: "정보있음", empty: "정보없음", error: "조회실패" };

function csvCell(value) {
  const text = String(value ?? "");
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function buildCsv() {
  const lines = [CSV_HEADER.join(",")];
  for (const unit of state.units.values()) {
    const f = unit.fields || {};
    const houseType = f["주택형"] || "";
    lines.push([
      unit.dong, unit.ho,
      houseType ? shortType(houseType) : "",
      STATUS_LABEL[unit.status] || unit.status,
      ...CSV_HEADER.slice(4).map((key) => f[key] || ""),
    ].map(csvCell).join(","));
  }
  // 엑셀에서 바로 열리도록 UTF-8 BOM 을 붙인다
  return "﻿" + lines.join("\n") + "\n";
}

function downloadCsv() {
  const blob = new Blob([buildCsv()], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${state.complex ? state.complex.name : "scan"}.csv`;
  document.body.append(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function renderActions(summary) {
  const bar = document.createElement("div");
  bar.className = "actions";

  const button = document.createElement("button");
  button.className = "btn";
  button.textContent = "CSV Download";
  button.addEventListener("click", downloadCsv);
  bar.append(button);

  el("empty-list").prepend(bar);
  if (summary.error) renderRetry(summary, bar);
}
```

- [ ] **Step 4: 재시도에서 token 을 없앤다**

`renderRetry` 안쪽 `params` 에서 `token` 줄을 지운다. 서버가 결과를 보관하지 않으므로 보낼 곳이 없다:

```javascript
      const params = new URLSearchParams({
        hm: state.complex.house_manage_no,
        pb: state.complex.pblanc_no,
        dong: unit.dong,
        ho: unit.ho,
      });
```

- [ ] **Step 5: 브라우저에서 확인한다**

```bash
python3 app.py
```

`상봉 센트럴` 을 검색해 스캔한다.

Expected — 값이 이전과 같아야 한다:
- 진행률이 `동·호 목록을 불러오는 중…` → `0 / 242` → 숫자 증가 → `완료 · 242세대 중 정보없음 18건`
- 격자가 실시간으로 채워진다
- 타입별 현황표에 84C `6`, 합계 `18`
- `CSV DOWNLOAD` 를 누르면 `상봉 센트럴 아이파크.csv` 가 받아지고 엑셀에서 한글이 안 깨진다
- 스캔 도중 `STOP` 을 누르면 곧 멈추고 `중단됨 · N세대까지 조회` 가 뜬다

- [ ] **Step 6: 커밋**

```bash
git add public/index.html
git commit -m "feat: 스캔 루프와 CSV 생성을 브라우저로 이전"
```

---

### Task 4: 정리와 배포 설정

**Files:**
- Delete: `scanner.py`, `tests/test_scanner.py`
- Modify: `tests/test_live.py`
- Create: `vercel.json`
- Modify: `README.md`

**Interfaces:**
- Consumes: 전체
- Produces: 없음

- [ ] **Step 1: `scanner.py` 와 그 테스트를 지운다**

스캔 오케스트레이션이 브라우저로 옮겨가 쓰이는 곳이 없다.

```bash
git rm scanner.py tests/test_scanner.py
```

- [ ] **Step 2: 라이브 회귀 테스트에서 scanner 의존을 걷어낸다**

`tests/test_live.py` 를 아래로 교체한다. 검증 값은 그대로다:

```python
"""청약홈에 실제로 붙는 회귀 테스트.

2026-07-24 실측값을 기준으로 삼는다. 청약홈 데이터가 갱신되면 값이 달라질 수 있으므로
기본으로는 건너뛰고, APPLYHOME_LIVE=1 일 때만 돈다.

    APPLYHOME_LIVE=1 python3 -m unittest tests.test_live -v
"""

import os
import pathlib
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import applyhome

LIVE = os.environ.get("APPLYHOME_LIVE") == "1"

SANGBONG = ("2025000439", "2025000439")
EXPECTED_EMPTY_101 = {"305", "502", "603", "1105", "1401", "1404", "1405", "2004", "2302", "2303"}


@unittest.skipUnless(LIVE, "APPLYHOME_LIVE=1 일 때만 실행합니다")
class LiveTest(unittest.TestCase):
    def test_상봉_101동_정보없음_10건이_그대로다(self):
        hm, pb = SANGBONG
        dongs = applyhome.list_dongs(hm, pb)
        target = next(d for d in dongs if d.name == "101")
        hos = applyhome.list_hos(hm, pb, target.sn)
        self.assertEqual(len(hos), 119, "101동 세대 수가 119가 아닙니다")

        with ThreadPoolExecutor(max_workers=4) as pool:
            units = list(pool.map(
                lambda ho: applyhome.fetch_detail(hm, pb, "101", ho.no), hos))

        empties = {u.ho for u in units if u.status == "empty"}
        self.assertEqual(empties, EXPECTED_EMPTY_101)

    def test_장위_1001동_201호는_정보가_있다(self):
        unit = applyhome.fetch_detail("2026000275", "2026000275", "1001", "201")
        self.assertEqual(unit.status, "info")
        self.assertEqual(unit.fields["주택명"], "장위 푸르지오 마크원")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: `vercel.json` 을 만든다**

```json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "functions": {
    "api/**/*.py": {
      "excludeFiles": "{tests/**,docs/**,**/test_*.py}"
    }
  }
}
```

테스트·문서·fixture 를 함수 번들에서 뺀다. fixture HTML 만 100KB 를 넘는다.
`applyhome.py` 와 `grid.py` 는 제외 대상이 아니므로 번들에 포함된다.

- [ ] **Step 4: 전체 테스트를 돌린다**

Run: `python3 -m unittest discover -s tests`
Expected: PASS — 74개, skipped 2
(파싱 47 + test_api 20 + test_server_search 5 + 라이브 2 = 74. 파싱 47 은
test_parse_list 5 + test_parse_dongho 7 + test_parse_detail 9 + test_grid 13 + test_pblanc 13)

- [ ] **Step 5: 라이브 회귀 테스트를 돌린다**

Run: `APPLYHOME_LIVE=1 python3 -m unittest tests.test_live -v`
Expected: PASS — 2개. 상봉 101동 정보없음 10건이 그대로여야 한다

- [ ] **Step 6: `README.md` 를 갱신한다**

「실행」 절을 아래로 교체한다:

```markdown
## 쓰는 법

### 배포된 주소로 (설치 없음)

Vercel 에 배포하면 브라우저에서 주소만 열면 된다. 설치할 것이 없다.

### 내 컴퓨터에서

```bash
python3 app.py
```

브라우저가 `http://127.0.0.1:8765` 로 열린다. 설치할 패키지는 없다 (표준 라이브러리만 쓴다).

## 직접 배포하기

1. 이 저장소를 fork 한다
2. [vercel.com](https://vercel.com) 에 GitHub 계정으로 가입한다
3. `Add New… → Project` 에서 fork 한 저장소를 고른다
4. 설정을 건드리지 않고 `Deploy` 를 누른다 — `vercel.json` 이 이미 들어 있다

개인 용도라면 Hobby 플랜으로 무료다. 이후 저장소에 푸시할 때마다 자동 배포된다.
```

「구조」 절의 표에서 `scanner.py` 행을 지우고 아래 두 행을 넣는다:

```markdown
| `api/_lib.py` | 엔드포인트 로직. 로컬 서버와 Vercel 함수가 함께 쓴다 |
| `api/*.py` | Vercel 서버리스 진입점 |
```

`| static/index.html |` 을 `| public/index.html |` 로 고친다.

「테스트」 절의 건수를 고친다:

```markdown
기본 실행은 74건이며 그중 라이브 2건은 건너뛴다.
```

- [ ] **Step 7: 커밋**

```bash
git add -A
git commit -m "chore: scanner 제거, vercel.json 추가, 문서 갱신"
```

---

## 완료 기준

- [ ] `python3 -m unittest discover -s tests` 가 74건 통과한다 (라이브 2건 skip)
- [ ] `python3 app.py` 로 로컬 실행이 그대로 동작한다
- [ ] 상봉 스캔 결과가 이전과 같다 — 242세대 / 정보없음 18건 / 특별 92 · 일반 132
- [ ] `CSV DOWNLOAD` 로 파일이 받아지고 엑셀에서 한글이 깨지지 않는다
- [ ] 스캔 도중 `STOP` 이 동작한다
- [ ] `scanner.py` 가 저장소에 없다
- [ ] `api/` 에 `_lib.py` 와 진입점 5개가 있다
- [ ] `vercel.json` 이 있고 `public/index.html` 이 있다
