# Visitor Counter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** footer에 "방문 오늘 N · 전체 M"을 표시한다. 1회 기준은 브라우저당 하루 1회이고, 날짜 판정은 서버의 KST 시계가 맡는다.

**Architecture:** 브라우저가 `localStorage`에 마지막으로 카운트된 날짜를 적어두고 페이지 로드 때 서버에 보낸다. 서버는 자기 KST 오늘과 비교해 `n`(0 또는 1)을 정하고, 항상 같은 모양의 Redis 파이프라인(`INCRBY`×2 + `EXPIRE`)을 보낸다. Redis를 못 쓰면 세 값을 `null`로 돌려주고 화면은 숫자를 감춘 채로 둔다.

**Tech Stack:** Python 표준 라이브러리, 기존 Upstash Redis REST 계층(`api/_cache.py`), ES 모듈, `unittest` + `node --test`

**작업 위치:** `feat/vercel-deploy` 브랜치 (`.worktrees/vercel-deploy` 워크트리). 모든 경로는 이 워크트리 기준이다.

**선행 스펙:** [`docs/superpowers/specs/2026-08-04-visitor-counter-design.md`](../specs/2026-08-04-visitor-counter-design.md)

## Global Constraints

- 새 의존성을 추가하지 않는다. Python은 표준 라이브러리만, 브라우저는 내장 API만 쓴다
- docstring·주석·테스트 메서드 이름·UI 문구를 전부 한국어로 쓴다. 주석은 "무엇"이 아니라 "왜"를 적는다
- **Redis 키는 서버 시계에서만 만든다.** 클라이언트가 보낸 `last`는 문자열 비교에만 쓰고 키 조립에 넣지 않는다
- `/api/visits`는 어떤 실패에도 `200`을 돌려주며 응답 모양은 `{"today", "day", "total"}` 하나뿐이다
- 카운터 실패가 스캔에 영향을 주면 안 된다. 예외는 전부 삼킨다
- 새 색·테두리·아이콘·애니메이션을 넣지 않는다. 기존 `caption` 계층(12px · `--muted`)을 그대로 쓴다
- 스캔 캐시 schema(`scan:v1:`), freshness 정책, 검색·스캔·CSV 동작을 건드리지 않는다

## File Structure

| 파일 | 책임 | 구분 |
|---|---|---|
| `api/_cache.py` | `kst_date()` · `visit_day_key()` · `CacheStore.count_visit()` | 수정 |
| `api/_lib.py` | `visits(query)`, `ROUTES`에 `/api/visits` 등록 | 수정 |
| `api/visits.py` | Vercel 진입점. 기존 진입점 6개와 같은 형태 | 추가 |
| `public/visits.mjs` | 저장된 날짜 읽기·쓰기, 표시 문자열 조립 | 추가 |
| `public/index.html` | footer span, 모듈 최상위에서 호출 | 수정 |
| `tests/test_cache.py` | 날짜 헬퍼와 파이프라인 검증 | 수정 |
| `tests/test_api.py` | `visits()` 계약, 경로 등록 | 수정 |
| `tests/test_visits.mjs` | 프런트엔드 순수 로직, footer 마크업 | 추가 |
| `README.md` | 구조표, 저장 내용 고지 정정, 테스트 건수 | 수정 |

브라우저 쪽 순수 로직을 `visits.mjs`로 빼는 이유는 `cache.mjs`와 같다 — `node --test`로 검증하기 위해서다. `index.html`에는 DOM을 만지는 몇 줄만 남긴다.

---

### Task 1: KST 날짜와 방문 키 헬퍼

**Files:**
- Modify: `api/_cache.py` (상수는 20번째 줄 `UNIT_STATUSES` 아래, 함수는 `complex_key` 근처)
- Test: `tests/test_cache.py`

**Interfaces:**
- Consumes: 기존 `_part(value, limit)` (`api/_cache.py`), `DAY_SECONDS`
- Produces:
  - `kst_date(now: float) -> str` — UTC epoch → `"YYYY-MM-DD"` (KST)
  - `visit_day_key(date: str) -> str` — `"visits:day:YYYY-MM-DD"`. 형식이 어긋나면 `ValueError`
  - `VISITS_TOTAL_KEY = "visits:total"`, `VISITS_DAY_TTL = 172800`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_cache.py`의 `KeySchemaTest` 클래스 바로 위에 붙인다.

```python
# 2026-08-03T15:00:00Z 가 KST 2026-08-04T00:00:00 이다. 경계 직전은 1초 뒤가 아니라 1초 앞이다.
VISIT_NOW = 1785812400          # 2026-08-04 12:00 KST
KST_MIDNIGHT = 1785769200       # 2026-08-04 00:00 KST
KST_BEFORE_MIDNIGHT = 1785769199  # 2026-08-03 23:59:59 KST


class KstDateTest(unittest.TestCase):
    def test_UTC_15시가_되면_KST_다음날이다(self):
        self.assertEqual(_cache.kst_date(KST_MIDNIGHT), "2026-08-04")

    def test_UTC_15시_직전은_KST_같은날이다(self):
        self.assertEqual(_cache.kst_date(KST_BEFORE_MIDNIGHT), "2026-08-03")

    def test_낮_시각도_같은_날짜다(self):
        self.assertEqual(_cache.kst_date(VISIT_NOW), "2026-08-04")

    def test_날짜키는_KST_날짜로_만든다(self):
        self.assertEqual(_cache.visit_day_key("2026-08-04"), "visits:day:2026-08-04")

    def test_형식이_어긋난_날짜는_거부한다(self):
        with self.assertRaises(ValueError):
            _cache.visit_day_key("2026-08-04T00:00:00")
```

- [ ] **Step 2: 테스트를 돌려 실패를 확인한다**

Run: `python3 -m unittest tests.test_cache.KstDateTest -v`
Expected: FAIL — `AttributeError: module '_cache' has no attribute 'kst_date'`

- [ ] **Step 3: 구현한다**

`api/_cache.py` 상단 import에 `datetime`을 더한다 (`import json` 위, 알파벳 순서).

```python
import datetime
```

`UNIT_STATUSES = frozenset({"info", "empty", "error"})` 아래에 상수를 더한다.

```python
# Vercel 함수는 UTC 로 돈다. 그냥 두면 한국 사용자에게 "오늘" 이 오전 9시에 바뀐다.
# 한국은 서머타임이 없으므로 고정 +9 오프셋이 정확하다.
KST = datetime.timezone(datetime.timedelta(hours=9))
VISITS_TOTAL_KEY = "visits:total"
VISITS_DAY_TTL = 2 * DAY_SECONDS
```

`complex_key` 함수 아래에 헬퍼 두 개를 더한다.

```python
def kst_date(now: float) -> str:
    """UTC epoch 를 KST 날짜 문자열로 바꾼다."""
    return datetime.datetime.fromtimestamp(now, KST).strftime("%Y-%m-%d")


def visit_day_key(date: str) -> str:
    """날짜별 방문자 키. kst_date() 가 돌려준 값만 받는다."""
    return f"visits:day:{_part(date, 10)}"
```

- [ ] **Step 4: 테스트를 돌려 통과를 확인한다**

Run: `python3 -m unittest tests.test_cache.KstDateTest -v`
Expected: PASS (5건)

- [ ] **Step 5: 커밋**

```bash
git add api/_cache.py tests/test_cache.py
git commit -m "feat: KST 날짜와 방문자 키 헬퍼 추가"
```

---

### Task 2: 방문 집계 파이프라인

**Files:**
- Modify: `api/_cache.py` (`CacheStore` 클래스 끝, `record_unit_error` 아래)
- Test: `tests/test_cache.py`

**Interfaces:**
- Consumes: Task 1의 `kst_date()`, `visit_day_key()`, `VISITS_TOTAL_KEY`, `VISITS_DAY_TTL`. 기존 `CacheStore.transport.pipeline()`, `CacheStore.now()`, `CacheUnavailable`
- Produces: `CacheStore.count_visit(last: str = "") -> dict | None` — 성공하면 `{"today": str, "day": int, "total": int}`, 실패하면 `None`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_cache.py`의 `FakeTransport` 정의 아래에 붙인다. `FakeTransport`는 이미 있으므로 새로 만들지 않는다.

```python
class CountVisitTest(unittest.TestCase):
    def store(self, transport):
        return _cache.CacheStore(transport, now=lambda: VISIT_NOW)

    def test_어제_방문자는_오늘_처음이라_1을_더한다(self):
        transport = FakeTransport([[3456, 12, 1]])
        result = self.store(transport).count_visit("2026-08-03")
        self.assertEqual(result, {"today": "2026-08-04", "day": 12, "total": 3456})
        self.assertEqual(transport.calls[0], [
            ["INCRBY", "visits:total", 1],
            ["INCRBY", "visits:day:2026-08-04", 1],
            ["EXPIRE", "visits:day:2026-08-04", 172800],
        ])

    def test_오늘_이미_센_방문자는_0을_더한다(self):
        transport = FakeTransport([[3456, 12, 1]])
        result = self.store(transport).count_visit("2026-08-04")
        self.assertEqual(result, {"today": "2026-08-04", "day": 12, "total": 3456})
        self.assertEqual(transport.calls[0], [
            ["INCRBY", "visits:total", 0],
            ["INCRBY", "visits:day:2026-08-04", 0],
            ["EXPIRE", "visits:day:2026-08-04", 172800],
        ])

    def test_last가_없으면_새_방문자로_센다(self):
        transport = FakeTransport([[1, 1, 1]])
        self.store(transport).count_visit("")
        self.assertEqual(transport.calls[0][0][2], 1)

    def test_이상한_last는_키를_오염시키지_않는다(self):
        transport = FakeTransport([[1, 1, 1]])
        self.store(transport).count_visit("../../etc/passwd")
        self.assertEqual(transport.calls[0][1][1], "visits:day:2026-08-04")
        self.assertEqual(transport.calls[0][0][2], 1)

    def test_Redis가_죽으면_None이다(self):
        transport = FakeTransport([_cache.CacheUnavailable("down")])
        self.assertIsNone(self.store(transport).count_visit("2026-08-03"))

    def test_형식이_어긋난_응답은_None이다(self):
        transport = FakeTransport([[None, None, 1]])
        self.assertIsNone(self.store(transport).count_visit("2026-08-03"))

    def test_응답_개수가_모자라면_None이다(self):
        transport = FakeTransport([[3456]])
        self.assertIsNone(self.store(transport).count_visit("2026-08-03"))
```

- [ ] **Step 2: 테스트를 돌려 실패를 확인한다**

Run: `python3 -m unittest tests.test_cache.CountVisitTest -v`
Expected: FAIL — `AttributeError: 'CacheStore' object has no attribute 'count_visit'`

- [ ] **Step 3: 구현한다**

`api/_cache.py`의 `CacheStore` 클래스 맨 끝(`record_unit_error` 아래)에 붙인다.

```python
    def count_visit(self, last: str = "") -> dict | None:
        """방문을 센다. last 가 KST 오늘과 다르면 1을 더하고, 같으면 현재 값만 읽는다.

        INCRBY 0 은 값을 바꾸지 않고 현재 값을 돌려주므로 신규와 재방문이 한 경로로 합쳐진다.
        키는 서버 시계로만 만든다. last 는 비교에만 쓰므로 어떤 값이 와도 키를 오염시키지 못한다.
        """
        today = kst_date(self.now())
        increment = 0 if last == today else 1
        day_key = visit_day_key(today)
        try:
            total, day, _ = self.transport.pipeline([
                ["INCRBY", VISITS_TOTAL_KEY, increment],
                ["INCRBY", day_key, increment],
                ["EXPIRE", day_key, VISITS_DAY_TTL],
            ])
            return {"today": today, "day": int(day), "total": int(total)}
        except (CacheUnavailable, TypeError, ValueError):
            return None
```

- [ ] **Step 4: 테스트를 돌려 통과를 확인한다**

Run: `python3 -m unittest tests.test_cache -v`
Expected: PASS — `KstDateTest` 5건과 `CountVisitTest` 7건을 포함해 기존 테스트가 모두 통과

- [ ] **Step 5: 커밋**

```bash
git add api/_cache.py tests/test_cache.py
git commit -m "feat: 방문자 집계 파이프라인 추가"
```

---

### Task 3: `/api/visits` 엔드포인트

**Files:**
- Modify: `api/_lib.py` (`cache_snapshot` 아래, `ROUTES`는 232번째 줄)
- Create: `api/visits.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: Task 2의 `CacheStore.count_visit(last)`. 기존 `_cache_call(method, *args)`, `one(query, key, default="")`
- Produces: `_lib.visits(query: dict) -> tuple[int, dict]` — 언제나 `(200, {"today", "day", "total"})`. `ROUTES["/api/visits"]`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_api.py`의 `RoutesTest` 바로 위에 붙인다. 기존 `FakeCache`는 건드리지 않고 이 테스트만의 대역을 쓴다.

```python
class VisitsTest(unittest.TestCase):
    def setUp(self):
        self.original_cache = _lib.CACHE
        self.calls = []
        outer = self

        class Counter:
            def count_visit(self, last):
                outer.calls.append(last)
                return {"today": "2026-08-04", "day": 12, "total": 3456}

        _lib.CACHE = Counter()

    def tearDown(self):
        _lib.CACHE = self.original_cache

    def test_방문자_수를_돌려준다(self):
        status, body = _lib.visits(q(last="2026-08-03"))
        self.assertEqual(status, 200)
        self.assertEqual(body, {"today": "2026-08-04", "day": 12, "total": 3456})
        self.assertEqual(self.calls, ["2026-08-03"])

    def test_last가_없어도_동작한다(self):
        status, body = _lib.visits({})
        self.assertEqual(status, 200)
        self.assertEqual(self.calls, [""])

    def test_지나치게_긴_last는_빈_값으로_취급한다(self):
        _lib.visits(q(last="x" * 33))
        self.assertEqual(self.calls, [""])

    def test_경계인_32자는_그대로_넘긴다(self):
        _lib.visits(q(last="x" * 32))
        self.assertEqual(self.calls, ["x" * 32])

    def test_cache가_없으면_값이_모두_None이다(self):
        _lib.CACHE = None
        status, body = _lib.visits(q(last="2026-08-03"))
        self.assertEqual(status, 200)
        self.assertEqual(body, {"today": None, "day": None, "total": None})

    def test_cache_예외는_값이_모두_None이다(self):
        class Broken:
            def count_visit(self, last):
                raise RuntimeError("redis secret detail")

        _lib.CACHE = Broken()
        status, body = _lib.visits(q(last="2026-08-03"))
        self.assertEqual(status, 200)
        self.assertEqual(body, {"today": None, "day": None, "total": None})

    def test_count_visit이_None이면_값이_모두_None이다(self):
        class Empty:
            def count_visit(self, last):
                return None

        _lib.CACHE = Empty()
        status, body = _lib.visits(q(last="2026-08-03"))
        self.assertEqual(status, 200)
        self.assertEqual(body, {"today": None, "day": None, "total": None})
```

같은 파일의 `RoutesTest`를 통째로 바꾼다. 경로가 여섯에서 일곱으로 늘어난다.

```python
class RoutesTest(unittest.TestCase):
    def test_일곱_경로가_등록되어_있다(self):
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
```

- [ ] **Step 2: 테스트를 돌려 실패를 확인한다**

Run: `python3 -m unittest tests.test_api.VisitsTest tests.test_api.RoutesTest -v`
Expected: FAIL — `AttributeError: module '_lib' has no attribute 'visits'`

- [ ] **Step 3: `_lib.visits` 를 구현한다**

`api/_lib.py`의 `cache_snapshot` 함수 아래, `ROUTES` 위에 붙인다.

```python
# last 는 비교에만 쓰지만 무한정 긴 값을 그대로 다룰 이유는 없다.
VISIT_LAST_MAX = 32


def visits(query: dict) -> tuple[int, dict]:
    """방문자 수. 부가 정보이므로 어떤 실패든 세 값을 None 으로 돌려준다.

    화면은 값이 None 이면 숫자를 감춘 채로 둔다. 카운터는 스캔에 영향을 주지 않는다.
    """
    last = one(query, "last")
    if len(last) > VISIT_LAST_MAX:
        last = ""
    counted = _cache_call("count_visit", last)
    if not counted:
        return 200, {"today": None, "day": None, "total": None}
    return 200, counted
```

`ROUTES`에 경로를 더한다.

```python
ROUTES = {
    "/api/search": search,
    "/api/dongs": dongs,
    "/api/hos": hos,
    "/api/unit": unit,
    "/api/pblanc": pblanc,
    "/api/cache": cache_snapshot,
    "/api/visits": visits,
}
```

- [ ] **Step 4: Vercel 진입점을 만든다**

`api/visits.py` 를 새로 만든다. 기존 `api/cache.py` 와 같은 형태다.

```python
"""Vercel 방문자 집계 진입점. 로직은 _lib 에 있다."""

import pathlib
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import _lib


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _lib.respond(self, *_lib.visits(query))
```

- [ ] **Step 5: 테스트를 돌려 통과를 확인한다**

Run: `python3 -m unittest discover -s tests`
Expected: PASS — 라이브 2건만 skip

- [ ] **Step 6: 커밋**

```bash
git add api/_lib.py api/visits.py tests/test_api.py
git commit -m "feat: /api/visits 엔드포인트 추가"
```

---

### Task 4: 브라우저 쪽 순수 로직

**Files:**
- Create: `public/visits.mjs`
- Test: `tests/test_visits.mjs`

**Interfaces:**
- Consumes: 없음 (순수 모듈)
- Produces:
  - `LAST_VISIT_KEY = "visits:last"`
  - `readLastDate(storage) -> string` — 없거나 저장소가 막혀 있으면 `""`
  - `saveLastDate(storage, date) -> boolean`
  - `formatVisits(payload) -> string | null` — `{day, total}`이 숫자면 `"오늘 12 · 전체 3,456"`, 아니면 `null`
  - `applyVisits(storage, payload) -> string | null` — 셀 수 있었을 때만 날짜를 저장하고 문자열을 돌려준다

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_visits.mjs` 를 새로 만든다. `index.html` 마크업 검증은 Task 5에서 붙이므로 여기서는 순수 로직만 다룬다.

```javascript
import test from "node:test";
import assert from "node:assert/strict";
import {
  LAST_VISIT_KEY, applyVisits, formatVisits, readLastDate, saveLastDate,
} from "../public/visits.mjs";

function memoryStorage(initial = {}) {
  const data = new Map(Object.entries(initial));
  return {
    getItem: (key) => (data.has(key) ? data.get(key) : null),
    setItem: (key, value) => data.set(key, value),
    read: (key) => data.get(key),
  };
}

function brokenStorage() {
  return {
    getItem() { throw new Error("blocked"); },
    setItem() { throw new Error("blocked"); },
  };
}

test("저장된 날짜가 없으면 빈 문자열이다", () => {
  assert.equal(readLastDate(memoryStorage()), "");
});

test("저장된 날짜를 읽는다", () => {
  const storage = memoryStorage({ [LAST_VISIT_KEY]: "2026-08-03" });
  assert.equal(readLastDate(storage), "2026-08-03");
});

test("저장소가 막혀 있어도 빈 문자열로 넘어간다", () => {
  assert.equal(readLastDate(brokenStorage()), "");
  assert.equal(saveLastDate(brokenStorage(), "2026-08-04"), false);
});

test("날짜를 저장한다", () => {
  const storage = memoryStorage();
  assert.equal(saveLastDate(storage, "2026-08-04"), true);
  assert.equal(storage.read(LAST_VISIT_KEY), "2026-08-04");
});

test("천 단위 쉼표를 넣어 표시한다", () => {
  assert.equal(
    formatVisits({ today: "2026-08-04", day: 12, total: 3456 }),
    "오늘 12 · 전체 3,456",
  );
});

test("숫자가 아니면 null 이다", () => {
  assert.equal(formatVisits({ today: null, day: null, total: null }), null);
  assert.equal(formatVisits(undefined), null);
});

test("셀 수 있었을 때만 날짜를 저장한다", () => {
  const storage = memoryStorage();
  const text = applyVisits(storage, { today: "2026-08-04", day: 12, total: 3456 });
  assert.equal(text, "오늘 12 · 전체 3,456");
  assert.equal(storage.read(LAST_VISIT_KEY), "2026-08-04");
});

test("세지 못했으면 날짜를 저장하지 않는다", () => {
  const storage = memoryStorage();
  assert.equal(applyVisits(storage, { today: null, day: null, total: null }), null);
  assert.equal(storage.read(LAST_VISIT_KEY), undefined);
});
```

- [ ] **Step 2: 테스트를 돌려 실패를 확인한다**

Run: `node --test tests/test_visits.mjs`
Expected: FAIL — `Cannot find module .../public/visits.mjs`

- [ ] **Step 3: 구현한다**

`public/visits.mjs` 를 새로 만든다.

```javascript
export const LAST_VISIT_KEY = "visits:last";

// 사생활 보호 모드나 저장소 차단 설정에서는 접근 자체가 예외를 던진다.
// 그때는 매번 새 방문으로 세어질 뿐, 카운터는 계속 동작해야 한다.
export function readLastDate(storage) {
  try {
    return storage?.getItem(LAST_VISIT_KEY) || "";
  } catch {
    return "";
  }
}

export function saveLastDate(storage, date) {
  if (typeof date !== "string" || !date) return false;
  try {
    storage?.setItem(LAST_VISIT_KEY, date);
    return true;
  } catch {
    return false;
  }
}

export function formatVisits(payload) {
  const day = payload?.day;
  const total = payload?.total;
  if (!Number.isFinite(day) || !Number.isFinite(total)) return null;
  return `오늘 ${day.toLocaleString("ko-KR")} · 전체 ${total.toLocaleString("ko-KR")}`;
}

// 세지 못한 방문을 세었다고 기록하면, 그날 안에 Redis 가 살아나도 다시 세지 않게 된다.
// 그래서 날짜 저장은 숫자를 받아낸 경우로 한정한다.
export function applyVisits(storage, payload) {
  const text = formatVisits(payload);
  if (text === null) return null;
  saveLastDate(storage, payload.today);
  return text;
}
```

- [ ] **Step 4: 테스트를 돌려 통과를 확인한다**

Run: `node --test tests/test_visits.mjs`
Expected: PASS (8건)

- [ ] **Step 5: 커밋**

```bash
git add public/visits.mjs tests/test_visits.mjs
git commit -m "feat: 방문자 표시 로직 모듈 추가"
```

---

### Task 5: footer 표시와 배선

**Files:**
- Modify: `public/index.html` (마크업은 229번째 줄 `.footer-meta` 안, import는 238번째 줄 근처, 호출은 271번째 줄 `AREAS.forEach` 아래)
- Test: `tests/test_visits.mjs`

**Interfaces:**
- Consumes: Task 4의 `applyVisits(storage, payload)`, `readLastDate(storage)`. Task 3의 `GET /api/visits?last=…`
- Produces: `id="visits"` span (기본 `class="hide"`)과 그 안의 `id="visits-text"` span

- [ ] **Step 1: 실패하는 마크업 테스트를 쓴다**

`tests/test_visits.mjs` 맨 위 import 아래에 `indexHtml` 을 더한다.

```javascript
import { readFileSync } from "node:fs";

const indexHtml = readFileSync(new URL("../public/index.html", import.meta.url), "utf8");
```

파일 맨 끝에 테스트 두 건을 붙인다.

```javascript
test("footer 에 감춰진 방문자 span 이 있다", () => {
  const start = indexHtml.indexOf('<div class="footer-meta">');
  assert.notEqual(start, -1);
  const meta = indexHtml.slice(start, indexHtml.indexOf("</div>", start));
  assert.match(meta, /<span id="visits" class="hide">방문 <span id="visits-text"><\/span><\/span>/);
});

test("방문자 모듈을 불러와 페이지 로드 때 부른다", () => {
  assert.match(indexHtml, /from "\/visits\.mjs"/);
  assert.match(indexHtml, /\/api\/visits\?/);
});
```

- [ ] **Step 2: 테스트를 돌려 실패를 확인한다**

Run: `node --test tests/test_visits.mjs`
Expected: FAIL — 새 테스트 2건이 실패하고 기존 8건은 통과

- [ ] **Step 3: footer 마크업을 더한다**

`public/index.html` 의 `.footer-meta` 안, `개발자` span 아래에 붙인다. 새 CSS는 넣지 않는다 — `.hide` 와 `.footer-meta` 가 이미 있다.

```html
    <span id="visits" class="hide">방문 <span id="visits-text"></span></span>
```

- [ ] **Step 4: 모듈을 불러온다**

`public/index.html` 의 `} from "/cache.mjs";` 줄 바로 아래에 붙인다.

```javascript
import { applyVisits, readLastDate } from "/visits.mjs";
```

- [ ] **Step 5: 페이지 로드 때 부른다**

`AREAS.forEach((name) => { … });` 블록 아래에 붙인다.

```javascript
// 방문자 수는 부가 정보다. 어떤 실패든 조용히 감춘 채로 두고 스캔에는 영향을 주지 않는다.
(async () => {
  try {
    const params = new URLSearchParams({ last: readLastDate(window.localStorage) });
    const payload = await (await fetch("/api/visits?" + params)).json();
    const text = applyVisits(window.localStorage, payload);
    if (text === null) return;
    el("visits-text").textContent = text;
    el("visits").classList.remove("hide");
  } catch {
    // 카운터가 죽어도 화면의 나머지는 그대로 동작해야 한다
  }
})();
```

- [ ] **Step 6: 테스트를 돌려 통과를 확인한다**

Run: `node --test tests/*.mjs`
Expected: PASS — `test_visits.mjs` 10건과 기존 `test_frontend_cache.mjs` 41건이 모두 통과

- [ ] **Step 7: 브라우저에서 눈으로 확인한다**

```bash
python3 app.py
```

`http://127.0.0.1:8765` 에서 확인한다. **로컬에는 Redis 가 없으므로 footer 에 `방문` 이 보이지 않는 것이 정상이다.** 개발자 도구 Network 에서 `/api/visits` 가 `200` 에 `{"today":null,"day":null,"total":null}` 을 돌려주는지, Console 에 오류가 없는지, 검색과 스캔이 그대로 동작하는지 본다.

- [ ] **Step 8: 커밋**

```bash
git add public/index.html tests/test_visits.mjs
git commit -m "feat: footer에 방문자 수 표시"
```

---

### Task 6: 문서 갱신과 전체 회귀

**Files:**
- Modify: `README.md` (구조표 110번째 줄 근처, 공유 캐시 고지 44번째 줄, 테스트 건수 130번째 줄 근처)

**Interfaces:**
- Consumes: Task 1–5의 결과 전부
- Produces: 없음

- [ ] **Step 1: 저장 내용 고지를 정정한다**

`README.md` 의 `### 공유 캐시 연결` 절 마지막 문장이 지금은 이렇다.

> 90일 동안 아무도 조회하지 않은 단지 결과는 자동 삭제된다. 날짜별 변경 이력과 방문자 정보는 저장하지 않는다.

**카운터를 넣으면 이 문장이 거짓이 된다.** 다음으로 바꾼다.

> 90일 동안 아무도 조회하지 않은 단지 결과는 자동 삭제된다. 날짜별 변경 이력은 저장하지 않는다.
> 방문자는 날짜별·누적 합계만 세며, 개인을 식별하는 값은 저장하지 않는다.

- [ ] **Step 2: 구조표에 새 파일을 더한다**

`README.md` 의 `## 구조` 표에서 `public/index.html` 행 아래에 붙인다.

```markdown
| `public/visits.mjs` | 방문자 수 표시 로직 |
```

`api/visits.py` 는 표에 이미 있는 `api/*.py` 행이 덮으므로 따로 더하지 않는다.

- [ ] **Step 3: 실제 테스트 건수를 잰다**

```bash
python3 -m unittest discover -s tests 2>&1 | tail -3
node --test tests/*.mjs 2>&1 | tail -6
```

두 숫자를 그대로 받아 적는다. **추정치를 쓰지 않는다.**

- [ ] **Step 4: 테스트 건수를 갱신한다**

`README.md` 의 `## 테스트` 절에서 다음 문장의 두 숫자를 Step 3의 실측값으로 바꾼다.

> 기본 실행은 124건이며 그중 라이브 2건은 건너뛴다. 프런트엔드 테스트는 41건을 실행한다.

- [ ] **Step 5: 전체 회귀를 돌린다**

```bash
python3 -m unittest discover -s tests
node --test tests/*.mjs
```

Expected: 둘 다 실패 0건. Python 은 라이브 2건만 skip.

- [ ] **Step 6: 비밀값이 새지 않았는지 본다**

```bash
git diff main...HEAD | grep -iE "UPSTASH_REDIS_REST_TOKEN=|sunghoonk@gmail" || echo "없음"
```

Expected: `없음`

- [ ] **Step 7: 커밋**

```bash
git add README.md
git commit -m "docs: 방문자 카운터 반영"
```

---

## 완료 기준

- [ ] `python3 -m unittest discover -s tests` 가 실패 0건 (라이브 2건 skip)
- [ ] `node --test tests/*.mjs` 가 실패 0건
- [ ] `python3 app.py` 로 띄운 로컬에서 검색·스캔·CSV 가 그대로 동작하고, Redis 가 없으므로 `방문` 이 보이지 않는다
- [ ] `/api/visits` 가 Redis 유무와 관계없이 `200` 과 `{"today","day","total"}` 모양을 돌려준다
- [ ] Redis 키가 `visits:total` 과 `visits:day:<KST 날짜>` 둘뿐이고 `scan:v1:` 과 겹치지 않는다
- [ ] `README.md` 의 "방문자 정보는 저장하지 않는다" 문장이 정정되어 있다
- [ ] `api/visits.py` 가 있고 `ROUTES` 에 `/api/visits` 가 등록되어 있다

## 배포 뒤 확인

Vercel 에 올린 뒤 Upstash 가 연결된 환경에서 본다.

- [ ] footer 에 `방문 오늘 N · 전체 M` 이 보인다
- [ ] 새로고침해도 숫자가 오르지 않는다
- [ ] 브라우저 저장소를 지우고 다시 열면 오늘·전체가 각각 1씩 오른다
- [ ] Upstash 콘솔에서 `visits:day:<오늘>` 의 TTL 이 48시간 이하로 잡혀 있다
- [ ] 페이지 로드마다 서버리스 함수 호출 1건과 Upstash 명령 3개가 늘어난다. Hobby 플랜
      쿼터가 이전보다 빠르게 소비되므로 Vercel·Upstash 대시보드에서 사용량을 확인한다
