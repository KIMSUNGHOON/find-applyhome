# 타입·공급유형 구분 보기 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 스캔 결과를 주택형(타입) 단위로 집계해 보여주고, 격자에서 타입과 공급유형을 세대별로 식별할 수 있게 한다. 동 블록은 화면 가로 폭에 맞춰 배치한다.

**Architecture:** 청약홈 공고 상세(`selectAPTLttotPblancDetail.do`)를 추가로 조회해 타입별 `일반/특별/계` 세대수를 가져온다. 스캔 결과의 타입별 집계는 프론트가 라인(호수 끝 두 자리)에서 역산해 채우고, 공고 값과 교차 검증해 어긋나면 경고한다. 공고 조회가 실패해도 스캔은 그대로 동작한다.

**Tech Stack:** Python 3.14 표준 라이브러리만, 바닐라 JS. 기존 프로젝트와 동일.

선행 스펙: `docs/superpowers/specs/2026-07-24-type-and-supply-breakdown-design.md`

## Global Constraints

- **서드파티 패키지 금지.** 표준 라이브러리만 사용한다. 테스트 러너는 `unittest`.
- 테스트 실행: `python3 -m unittest discover -s tests -v`
- 기존 테스트 59건이 계속 통과해야 한다 (라이브 2건은 skip).
- **타입 축약 정규식** `^0*(\d+)\.\d+(.*)$` → `group(1) + group(2)`. Python·JS 양쪽에 동일하게 쓴다.
- **전용면적 추출 정규식** `^0*(\d+\.\d+)` → `group(1)`.
- **공고 테이블 식별** — `<caption>` 텍스트가 정확히 `입주자모집공고 공급대상` 인 테이블만 쓴다. 부분 문자열로 찾으면 `입주자모집공고 특별공급 공급대상` 까지 걸린다.
- **공고 행 파싱** — 위치 인덱스가 아니라 주택형 패턴(`^\d{2,4}\.\d{2,6}`)이 나온 셀을 기준점으로 `[i]=주택형, [i+1]=공급면적, [i+2]=일반, [i+3]=특별, [i+4]=계` 로 읽는다.
- **공고 조회 실패는 스캔을 막지 않는다.** 실패 시 `supply` 는 `None` 이고 화면은 `공고 대조 불가` 로 표시한다.
- 미계약 세대에는 공급유형이 존재하지 않는다. 격자 셀에 글자를 넣지 않고 색만 칠한다.

## 준비된 자산

`tests/fixtures/` 에 공고 응답 두 건이 저장되어 있다. 네트워크 없이 Task 1~3 을 진행할 수 있다.

| 파일 | 내용 | 실측값 |
|---|---|---|
| `pblanc_sangbong.html` | 상봉 센트럴 아이파크 공고 | 5개 타입, 합계 242세대 (일반 113 / 특별 129) |
| `pblanc_jangwi.html` | 장위 푸르지오 마크원 공고 | 18개 타입, 합계 1032세대, 타입 코드 없는 `046.8700` 포함 |

## File Structure

| 파일 | 이번 변경 |
|---|---|
| `applyhome.py` | `SupplyType` 데이터클래스, `parse_pblanc_supply`, `fetch_pblanc_supply` 추가 |
| `grid.py` | `short_type`, `net_area` 추가 |
| `scanner.py` | `meta` 이벤트에 `supply` 실어 보내기 |
| `server.py` | CSV 에 `타입` 컬럼 추가 |
| `static/index.html` | 현황표·격자 헤더·셀 글자·범례·교차검증·레이아웃 |
| `tests/test_pblanc.py` | 신규 — 공고 파싱 |
| `tests/test_grid.py` | 축약·전용면적 테스트 추가 |
| `tests/test_scanner.py` | `supply` 전달 테스트 추가 |
| `tests/test_export.py` | CSV 타입 컬럼 테스트 추가 |

---

### Task 1: `grid.py` — 타입 축약과 전용면적

**Files:**
- Modify: `grid.py` (파일 끝에 추가)
- Modify: `tests/test_grid.py` (파일 끝, `if __name__` 앞에 클래스 추가)

**Interfaces:**
- Consumes: 없음
- Produces: `short_type(house_type: str) -> str` — `"084.8422A"` → `"84A"`. 패턴에 안 맞으면 입력을 그대로 반환. `net_area(house_type: str) -> str` — `"084.8422A"` → `"84.8422"`. 안 맞으면 빈 문자열

- [ ] **Step 1: 실패하는 테스트 추가**

`tests/test_grid.py` 의 `if __name__ == "__main__":` 앞에 넣는다:

```python
class ShortTypeTest(unittest.TestCase):
    def test_전용면적_정수부와_타입코드를_붙인다(self):
        self.assertEqual(grid.short_type("084.8422A"), "84A")
        self.assertEqual(grid.short_type("039.7700A"), "39A")

    def test_타입코드가_없으면_숫자만_남는다(self):
        self.assertEqual(grid.short_type("046.8700"), "46")
        self.assertEqual(grid.short_type("114.2100"), "114")

    def test_두글자_타입코드도_유지한다(self):
        self.assertEqual(grid.short_type("059.9800A1"), "59A1")

    def test_형식이_다르면_입력을_그대로_돌려준다(self):
        self.assertEqual(grid.short_type("알수없음"), "알수없음")
        self.assertEqual(grid.short_type(""), "")


class NetAreaTest(unittest.TestCase):
    def test_앞자리_0을_버린_전용면적을_뽑는다(self):
        self.assertEqual(grid.net_area("084.8422A"), "84.8422")
        self.assertEqual(grid.net_area("046.8700"), "46.8700")
        self.assertEqual(grid.net_area("114.2100"), "114.2100")

    def test_형식이_다르면_빈_문자열이다(self):
        self.assertEqual(grid.net_area("알수없음"), "")
```

- [ ] **Step 2: 테스트를 돌려 실패를 확인한다**

Run: `python3 -m unittest tests.test_grid -v`
Expected: FAIL — `AttributeError: module 'grid' has no attribute 'short_type'`

- [ ] **Step 3: `grid.py` 에 구현 추가**

파일 상단 `from __future__ import annotations` 아래에 `import re` 를 추가하고, 파일 끝에 넣는다:

```python
# 주택형 "084.8422A" 는 전용면적 84.8422㎡ 와 타입 코드 A 가 붙은 문자열이다.
# 화면에는 "84A" 로 줄여 쓰고, 원본은 상세와 CSV 에 그대로 남긴다.
_SHORT_RE = re.compile(r"^0*(\d+)\.\d+(.*)$")
_NET_AREA_RE = re.compile(r"^0*(\d+\.\d+)")


def short_type(house_type: str) -> str:
    """주택형을 화면 표기용으로 줄인다. "084.8422A" → "84A"."""
    match = _SHORT_RE.match(house_type)
    return match.group(1) + match.group(2) if match else house_type


def net_area(house_type: str) -> str:
    """주택형에서 전용면적을 뽑는다. "084.8422A" → "84.8422".

    공고 테이블의 '주택공급면적'(주거전용+주거공용)과는 다른 값이다. 섞지 말 것.
    """
    match = _NET_AREA_RE.match(house_type)
    return match.group(1) if match else ""
```

- [ ] **Step 4: 테스트를 돌려 통과를 확인한다**

Run: `python3 -m unittest tests.test_grid -v`
Expected: PASS — 13개 테스트 (기존 7 + 신규 6) 전부 ok

- [ ] **Step 5: 커밋**

```bash
git add grid.py tests/test_grid.py
git commit -m "feat: 주택형 축약 표기와 전용면적 추출 추가"
```

---

### Task 2: `applyhome.py` — 공고 공급대상 파싱

**Files:**
- Modify: `applyhome.py` (URL 상수 추가, 파일 끝에 구현 추가)
- Create: `tests/test_pblanc.py`

**Interfaces:**
- Consumes: Task 1 의 `grid.short_type`(쓰지 않는다. 서버 직렬화 단계인 Task 3 에서 쓴다), 기존 `applyhome._text`
- Produces: `SupplyType(house_type: str, area: str, general: int, special: int, total: int)` 데이터클래스, `parse_pblanc_supply(html: str) -> list[SupplyType]`, `fetch_pblanc_supply(hm: str, pb: str) -> list[SupplyType]`, 상수 `PBLANC_URL`, `SUPPLY_CAPTION`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_pblanc.py`:

```python
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import applyhome

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


class ParseSangbongTest(unittest.TestCase):
    def setUp(self):
        html = (FIXTURES / "pblanc_sangbong.html").read_text(encoding="utf-8")
        self.types = applyhome.parse_pblanc_supply(html)
        self.by_type = {t.house_type: t for t in self.types}

    def test_타입_5개를_뽑는다(self):
        self.assertEqual(len(self.types), 5)

    def test_타입별_일반_특별_계가_정확하다(self):
        a = self.by_type["084.8422A"]
        self.assertEqual((a.general, a.special, a.total), (22, 23, 45))
        c = self.by_type["084.6747C"]
        self.assertEqual((c.general, c.special, c.total), (23, 28, 51))

    def test_공급면적을_담는다(self):
        self.assertEqual(self.by_type["084.8422A"].area, "116.9496")

    def test_합계가_공고_공급규모와_같다(self):
        self.assertEqual(sum(t.total for t in self.types), 242)
        self.assertEqual(sum(t.general for t in self.types), 113)
        self.assertEqual(sum(t.special for t in self.types), 129)

    def test_계_행은_타입으로_잡히지_않는다(self):
        for t in self.types:
            self.assertRegex(t.house_type, r"^\d{2,4}\.\d{2,6}")

    def test_주택구분_rowspan이_있는_첫행도_정확하다(self):
        # 첫 행에만 '민영' 이 붙어 셀이 하나 더 많다
        self.assertEqual(self.by_type["084.8422A"].total, 45)
        self.assertEqual(self.by_type["084.7662B"].total, 49)


class SpecialSupplyTableTest(unittest.TestCase):
    """'입주자모집공고 특별공급 공급대상' 표에 오염되지 않아야 한다."""

    def test_특별공급_세부표가_섞이지_않는다(self):
        html = (FIXTURES / "pblanc_sangbong.html").read_text(encoding="utf-8")
        types = applyhome.parse_pblanc_supply(html)
        # 세부표가 섞이면 타입이 10개가 되고 합계가 242 를 벗어난다
        self.assertEqual(len(types), 5)
        self.assertEqual(sum(t.total for t in types), 242)


class ParseJangwiTest(unittest.TestCase):
    def setUp(self):
        html = (FIXTURES / "pblanc_jangwi.html").read_text(encoding="utf-8")
        self.types = applyhome.parse_pblanc_supply(html)
        self.by_type = {t.house_type: t for t in self.types}

    def test_타입_18개와_합계_1032(self):
        self.assertEqual(len(self.types), 18)
        self.assertEqual(sum(t.total for t in self.types), 1032)

    def test_타입코드가_없는_주택형도_담는다(self):
        t = self.by_type["046.8700"]
        self.assertEqual((t.general, t.special, t.total), (6, 1, 7))

    def test_세자리_세대수도_정확하다(self):
        t = self.by_type["084.8700B"]
        self.assertEqual((t.general, t.special, t.total), (115, 136, 251))


class FailureToleranceTest(unittest.TestCase):
    def test_빈_HTML은_빈_리스트다(self):
        self.assertEqual(applyhome.parse_pblanc_supply(""), [])

    def test_캡션이_없으면_빈_리스트다(self):
        html = "<html><table><caption>다른 표</caption><tr><td>x</td></tr></table></html>"
        self.assertEqual(applyhome.parse_pblanc_supply(html), [])

    def test_숫자가_아닌_세대수는_건너뛴다(self):
        html = (
            "<table><caption>입주자모집공고 공급대상</caption>"
            "<tr><td>084.1111A</td><td>100.0</td><td>미정</td><td>미정</td><td>미정</td></tr>"
            "<tr><td>084.2222B</td><td>101.0</td><td>1</td><td>2</td><td>3</td></tr>"
            "</table>"
        )
        types = applyhome.parse_pblanc_supply(html)
        self.assertEqual(len(types), 1)
        self.assertEqual(types[0].house_type, "084.2222B")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 테스트를 돌려 실패를 확인한다**

Run: `python3 -m unittest tests.test_pblanc -v`
Expected: FAIL — `AttributeError: module 'applyhome' has no attribute 'parse_pblanc_supply'`

- [ ] **Step 3: `applyhome.py` 에 URL 상수 추가**

`DETAIL_URL` 정의 바로 아래에 넣는다:

```python
PBLANC_URL = f"{BASE}/ai/aia/selectAPTLttotPblancDetail.do"
```

- [ ] **Step 4: `applyhome.py` 파일 끝에 구현 추가**

```python
# 공고 상세 페이지에는 주택형을 담은 표가 두 개 있다.
#   '입주자모집공고 공급대상'          → 타입별 일반/특별/계  (이것을 쓴다)
#   '입주자모집공고 특별공급 공급대상'  → 특별공급 세부 분해   (쓰지 않는다)
# 부분 문자열로 찾으면 뒤엣것까지 걸리므로 캡션이 정확히 일치할 때만 받는다.
SUPPLY_CAPTION = "입주자모집공고 공급대상"

_SUPPLY_TYPE_RE = re.compile(r"^\d{2,4}\.\d{2,6}")


@dataclass(frozen=True)
class SupplyType:
    house_type: str   # "084.8422A" 원본 주택형
    area: str         # "116.9496" 주택공급면적(주거전용+주거공용)
    general: int      # 일반공급 세대수
    special: int      # 특별공급 세대수
    total: int        # 계


def parse_pblanc_supply(html: str) -> list[SupplyType]:
    """공고 상세 HTML 에서 타입별 공급세대수를 뽑는다.

    표를 못 찾거나 형식이 어긋나면 예외 대신 빈 리스트를 돌려준다.
    공고는 부가 정보라 스캔을 막아서는 안 된다.
    """
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    html = re.sub(r"<(script|style).*?</\1>", "", html, flags=re.S)

    for table in re.findall(r"<table[^>]*>(.*?)</table>", html, re.S):
        caption = re.search(r"<caption[^>]*>(.*?)</caption>", table, re.S)
        if caption is None or _text(caption.group(1)) != SUPPLY_CAPTION:
            continue

        types = []
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S):
            cells = [_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
            # 첫 행에만 주택구분(민영/국민)이 rowspan 으로 붙고, 마지막엔 '계' 행이 온다.
            # 그래서 위치가 아니라 주택형 패턴을 기준점으로 삼는다.
            for index, cell in enumerate(cells):
                if not _SUPPLY_TYPE_RE.match(cell) or index + 4 >= len(cells):
                    continue
                try:
                    types.append(
                        SupplyType(
                            house_type=cell,
                            area=cells[index + 1],
                            general=int(cells[index + 2]),
                            special=int(cells[index + 3]),
                            total=int(cells[index + 4]),
                        )
                    )
                except ValueError:
                    pass  # 세대수 자리에 숫자가 아닌 값이 온 행은 버린다
                break
        return types
    return []


def fetch_pblanc_supply(hm: str, pb: str) -> list[SupplyType]:
    """공고 상세를 조회해 타입별 공급세대수를 돌려준다.

    APT 전용 엔드포인트다. 오피스텔·도시형은 주소가 달라 빈 리스트가 나온다.
    """
    query = urllib.parse.urlencode({"houseManageNo": hm, "pblancNo": pb})
    request = urllib.request.Request(
        f"{PBLANC_URL}?{query}",
        headers={"User-Agent": USER_AGENT, "Referer": LIST_URL},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            html = response.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError):
        return []
    return parse_pblanc_supply(html)
```

- [ ] **Step 5: 테스트를 돌려 통과를 확인한다**

Run: `python3 -m unittest tests.test_pblanc -v`
Expected: PASS — 13개 테스트 전부 ok

- [ ] **Step 6: 전체 테스트로 회귀를 확인한다**

Run: `python3 -m unittest discover -s tests`
Expected: PASS — 78개 (기존 59 + Task 1 의 6 + 이번 13), skipped 2

- [ ] **Step 7: 커밋**

```bash
git add applyhome.py tests/test_pblanc.py
git commit -m "feat: 공고 상세에서 타입별 공급세대수 파싱 추가"
```

---

### Task 3: `scanner.py` — meta 에 공고 정보 싣기

**Files:**
- Modify: `scanner.py` (`on_event("meta", ...)` 부분)
- Modify: `tests/test_scanner.py` (FakeClient 에 메서드 추가, 테스트 클래스 추가)

**Interfaces:**
- Consumes: Task 1 의 `grid.short_type`·`grid.net_area`, Task 2 의 `applyhome.fetch_pblanc_supply`·`SupplyType`
- Produces: `meta` 이벤트에 `supply` 키. 값은 `[{"type","short","net_area","area","general","special","total"}]` 배열이거나, 공고를 못 얻으면 `None`

- [ ] **Step 1: 실패하는 테스트 추가**

`tests/test_scanner.py` 의 `FakeClient` 에 메서드를 하나 추가한다 (`fetch_detail` 아래):

```python
    def fetch_pblanc_supply(self, hm, pb):
        return getattr(self, "_supply", [])
```

그리고 `if __name__ == "__main__":` 앞에 클래스를 추가한다:

```python
class SupplyInMetaTest(unittest.TestCase):
    def _client(self, supply):
        client = FakeClient(
            dongs=[applyhome.Dong(1, "101")],
            hos={1: [applyhome.Ho(1, "201")]},
        )
        client._supply = supply
        return client

    def test_공고_정보가_meta에_실린다(self):
        client = self._client([
            applyhome.SupplyType("084.8422A", "116.9496", 22, 23, 45),
        ])
        events = collect(client)
        supply = events[0][1]["supply"]
        self.assertEqual(len(supply), 1)
        self.assertEqual(supply[0]["type"], "084.8422A")
        self.assertEqual(supply[0]["general"], 22)
        self.assertEqual(supply[0]["special"], 23)
        self.assertEqual(supply[0]["total"], 45)

    def test_축약과_전용면적이_함께_실린다(self):
        client = self._client([
            applyhome.SupplyType("084.8422A", "116.9496", 22, 23, 45),
        ])
        supply = collect(client)[0][1]["supply"]
        self.assertEqual(supply[0]["short"], "84A")
        self.assertEqual(supply[0]["net_area"], "84.8422")
        self.assertEqual(supply[0]["area"], "116.9496")

    def test_공고를_못_얻으면_None이다(self):
        events = collect(self._client([]))
        self.assertIsNone(events[0][1]["supply"])

    def test_공고_조회가_터져도_스캔은_계속된다(self):
        class Broken(FakeClient):
            def fetch_pblanc_supply(self, hm, pb):
                raise RuntimeError("공고 서버 오류")

        client = Broken(
            dongs=[applyhome.Dong(1, "101")],
            hos={1: [applyhome.Ho(1, "201")]},
        )
        events = collect(client)
        self.assertEqual(events[0][0], "meta")
        self.assertIsNone(events[0][1]["supply"])
        self.assertEqual(events[-1][0], "done")
```

- [ ] **Step 2: 테스트를 돌려 실패를 확인한다**

Run: `python3 -m unittest tests.test_scanner -v`
Expected: FAIL — `KeyError: 'supply'`

- [ ] **Step 3: `scanner.py` 수정**

`on_event("meta", {"total": len(jobs), "dongs": meta_dongs})` 한 줄을 아래로 교체한다:

```python
    on_event("meta", {"total": len(jobs), "dongs": meta_dongs, "supply": _supply(client, hm, pb)})
```

그리고 파일 끝에 헬퍼를 추가한다:

```python
def _supply(client, hm: str, pb: str) -> list[dict] | None:
    """공고에서 타입별 공급세대수를 가져온다.

    공고는 부가 정보다. 어떤 이유로 실패하든 None 을 돌려주고 스캔은 계속한다.
    """
    try:
        types = client.fetch_pblanc_supply(hm, pb)
    except Exception:
        return None
    if not types:
        return None
    return [
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
```

- [ ] **Step 4: 테스트를 돌려 통과를 확인한다**

Run: `python3 -m unittest tests.test_scanner -v`
Expected: PASS — 13개 테스트 (기존 9 + 신규 4) 전부 ok

- [ ] **Step 5: 커밋**

```bash
git add scanner.py tests/test_scanner.py
git commit -m "feat: 스캔 meta 에 공고 타입별 공급세대수 포함"
```

---

### Task 4: `server.py` — CSV 에 타입 컬럼

**Files:**
- Modify: `server.py` (`CSV_HEADER`, `build_csv`)
- Modify: `tests/test_export.py` (기대 헤더 수정, 테스트 추가)

**Interfaces:**
- Consumes: Task 1 의 `grid.short_type`
- Produces: CSV 헤더 `동,호,타입,판정,주택형,공급유형,공고일,당첨자 발표일,계약체결일,입주예정,전매제한,분양금액(만원)`

`타입` 은 `호` 와 `판정` 사이다. 기존 `build_csv` 는 `CSV_HEADER[3:]` 를 `fields` 에서 꺼내 썼는데,
컬럼이 하나 늘면서 그 슬라이스가 어긋난다. 아래 구현은 `CSV_HEADER[4:]` 로 고친 것이다.

- [ ] **Step 1: 기존 테스트의 기대 헤더를 고치고 테스트를 추가한다**

`tests/test_export.py` 의 `test_헤더가_명세대로다` 를 아래로 교체한다:

```python
    def test_헤더가_명세대로다(self):
        header = server.build_csv(UNITS).lstrip("﻿").splitlines()[0]
        self.assertEqual(
            header,
            "동,호,타입,판정,주택형,공급유형,공고일,당첨자 발표일,계약체결일,입주예정,전매제한,분양금액(만원)",
        )
```

`test_정보없음_행은_상세칸이_비어있다` 도 컬럼이 하나 늘었으므로 교체한다:

```python
    def test_정보없음_행은_타입만_있고_상세칸은_비어있다(self):
        lines = server.build_csv(UNITS).lstrip("﻿").strip().splitlines()
        self.assertEqual(lines[2], "101,305,,정보없음,,,,,,,,")
```

그리고 `BuildCsvTest` 안에 테스트를 추가한다:

```python
    def test_정보있음_행은_주택형에서_축약한_타입이_들어간다(self):
        lines = server.build_csv(UNITS).lstrip("﻿").strip().splitlines()
        self.assertEqual(lines[1].split(",")[2], "84A")

    def test_타입은_호와_판정_사이다(self):
        header = server.build_csv(UNITS).lstrip("﻿").splitlines()[0].split(",")
        self.assertEqual(header[1], "호")
        self.assertEqual(header[2], "타입")
        self.assertEqual(header[3], "판정")
```

`UNITS` 의 첫 항목 `주택형` 이 `084.9721` 이면 축약이 `84` 가 되어 위 테스트가 깨진다.
`UNITS[0]["fields"]["주택형"]` 값을 `"084.9721A"` 로 바꾼다:

```python
        "fields": {
            "주택형": "084.9721A",
```

- [ ] **Step 2: 테스트를 돌려 실패를 확인한다**

Run: `python3 -m unittest tests.test_export -v`
Expected: FAIL — 헤더가 `동,호,판정,...` 이라 `AssertionError`

- [ ] **Step 3: `server.py` 수정**

상단 import 에 `import grid` 를 추가한다 (`import applyhome` 아래).

`CSV_HEADER` 와 `build_csv` 를 아래로 교체한다:

```python
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
```

- [ ] **Step 4: 테스트를 돌려 통과를 확인한다**

Run: `python3 -m unittest tests.test_export -v`
Expected: PASS — 13개 테스트 (기존 11 + 신규 2) 전부 ok

- [ ] **Step 5: 전체 테스트로 회귀를 확인한다**

Run: `python3 -m unittest discover -s tests`
Expected: PASS — 84개, skipped 2

- [ ] **Step 6: 커밋**

```bash
git add server.py tests/test_export.py
git commit -m "feat: CSV 에 타입 컬럼 추가"
```

---

### Task 5: UI — 타입 축약 헬퍼와 레이아웃

**Files:**
- Modify: `static/index.html` (`<style>` 블록, `<script>` 상단)

**Interfaces:**
- Consumes: 없음
- Produces: JS 함수 `shortType(houseType)`, `netArea(houseType)`, `fmtArea(value)` — Task 6·7 이 쓴다. `fmtArea("116.9496")` → `"116.95㎡"`, 빈 입력이면 `""`

- [ ] **Step 1: 레이아웃 CSS 수정**

`body` 규칙을 찾아 `max-width: 1100px;` 를 `max-width: none;` 으로, `padding: 24px;` 를 `padding: 16px 20px;` 로 바꾼다. 바뀐 뒤 모습:

```css
  body { font-family: -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", sans-serif;
         margin: 0; padding: 16px 20px; max-width: none; line-height: 1.5; }
```

- [ ] **Step 2: 동 블록 가로 배치 CSS 추가**

`.dong { margin: 20px 0; }` 를 찾아 아래 두 규칙으로 교체한다:

```css
  /* 동을 가로로 흘려 배치한다. 장위처럼 동이 23개인 단지에서 세로 스크롤이 과도해진다. */
  #grids { display: flex; flex-wrap: wrap; gap: 20px 26px; align-items: flex-start; }
  .dong { margin: 0; }
```

- [ ] **Step 3: 범례와 목록 표 폭 조정**

`.legend` 규칙에 `flex-basis: 100%;` 를 넣는다. flex 컨테이너 안이라 이게 없으면 마지막 동 옆에 붙는다:

```css
  .legend { font-size: 12px; color: var(--dim); margin-top: 8px; flex-basis: 100%; }
```

`table.list` 규칙의 `width: 100%;` 를 `max-width: 820px; width: 100%;` 로 바꾼다:

```css
  table.list { border-collapse: collapse; font-size: 13px; margin-top: 8px;
               width: 100%; max-width: 820px; }
```

- [ ] **Step 4: JS 헬퍼 추가**

`<script>` 안, `const state = {...}` 선언 바로 아래에 넣는다:

```javascript
// 주택형 "084.8422A" → 표기 "84A", 전용면적 "84.8422".
// grid.py 의 short_type / net_area 와 같은 규칙이다. 한쪽만 고치면 화면 표기가 어긋난다.
function shortType(houseType) {
  const m = /^0*(\d+)\.\d+(.*)$/.exec(houseType || "");
  return m ? m[1] + m[2] : (houseType || "");
}

function netArea(houseType) {
  const m = /^0*(\d+\.\d+)/.exec(houseType || "");
  return m ? m[1] : "";
}

function fmtArea(value) {
  const n = parseFloat(value);
  return isNaN(n) ? "" : n.toFixed(2) + "㎡";
}
```

- [ ] **Step 5: 브라우저 콘솔에서 헬퍼를 확인한다**

```bash
python3 app.py
```

브라우저 개발자도구 콘솔에서 실행한다:

```javascript
[shortType("084.8422A"), shortType("046.8700"), shortType("059.9800A1"), shortType("114.2100")]
```

Expected: `["84A", "46", "59A1", "114"]` — Task 1 의 파이썬 테스트 기대값과 같아야 한다

```javascript
[netArea("084.8422A"), fmtArea("116.9496"), fmtArea("")]
```

Expected: `["84.8422", "116.95㎡", ""]`

- [ ] **Step 6: 화면에서 가로 배치를 확인한다**

`상봉 센트럴`을 검색해 스캔한다.
Expected: 101동과 102동이 **가로로 나란히** 놓이고, 좌우 여백이 거의 없다. 범례는 동 아래 줄바꿈되어 나온다.

- [ ] **Step 7: 커밋**

```bash
git add static/index.html
git commit -m "feat: 동 블록 가로 배치와 타입 표기 헬퍼 추가"
```

---

### Task 6: UI — 격자 헤더 타입과 셀 공급유형

**Files:**
- Modify: `static/index.html` (`.cell` CSS, `buildGridTable`, `makeCell`, `onUnit`, `onMeta`, 범례)

**Interfaces:**
- Consumes: Task 5 의 `shortType`, 기존 `state.units`
- Produces: `lineTypes(dongName)` — 그 동의 라인별 주택형을 `{라인: 주택형|"혼합"}` 으로 돌려준다. Task 7 의 현황표가 쓴다

- [ ] **Step 1: 셀 CSS 를 글자가 들어가게 고친다**

`.cell` 규칙을 아래로 교체한다. 26px 로는 `특`/`일` 한 글자가 들어가지 않는다:

```css
  /* 배경색은 상태(정보있음/없음/실패), 글자는 공급유형(특/일).
     색을 더 늘리면 다섯 가지가 되어 구분이 안 된다. */
  .cell { width: 30px; height: 24px; border: 1px solid var(--line); border-radius: 3px;
          background: transparent; cursor: pointer; font-size: 11px; color: transparent;
          overflow: hidden; padding: 0; line-height: 1; }
  .cell.info  { background: var(--info); color: #fff; }
  .cell.empty { background: var(--empty); color: transparent; }
  .cell.error { background: var(--err); color: transparent; }
```

`.flat .cell` 규칙도 폭을 맞춘다:

```css
  .flat .cell { width: 52px; color: inherit; overflow: visible; }
  .flat .cell.info, .flat .cell.empty, .flat .cell.error { color: #fff; }
```

헤더 2행용 스타일을 `table.grid th` 아래에 추가한다:

```css
  table.grid th.type { font-size: 10px; color: var(--dim); padding: 0 2px 3px; }
```

- [ ] **Step 2: `makeCell` 과 `onUnit` 을 공급유형 표기로 고친다**

기존 `makeCell` 과 `onUnit` 을 아래로 교체한다:

```javascript
function makeCell(dong, ho) {
  const button = document.createElement("button");
  button.className = "cell";
  button.id = cellId(dong, ho);
  button.title = `${dong}동 ${ho}호`;
  button.addEventListener("click", () => showDetail(dong, ho));
  return button;
}

const SUPPLY_MARK = { "특별공급": "특", "일반공급": "일" };

function onUnit(unit) {
  const cell = document.getElementById(cellId(unit.dong, unit.ho));
  if (!cell) return;
  cell.classList.add(unit.status);

  const type = unit.fields["주택형"] || "";
  const supply = unit.fields["공급유형"] || "";
  // 미계약·실패 세대에는 공급유형이 없다. 청약홈이 값을 주지 않으므로 글자를 비운다.
  cell.textContent = SUPPLY_MARK[supply] || "";
  cell.title =
    `${unit.dong}동 ${unit.ho}호` +
    (type ? ` · ${shortType(type)}` : "") +
    (supply ? ` · ${supply}` : "");
}
```

- [ ] **Step 3: 라인별 타입을 산출하는 함수를 추가한다**

`onUnit` 아래에 넣는다:

```javascript
// 라인(호수 끝 두 자리)마다 주택형을 모은다. 한 라인에 두 타입이 섞이면 "혼합".
// 정보있음 세대의 주택형에서 역산하므로 스캔이 진행되며 채워진다.
function lineTypes(dongName) {
  const found = new Map();
  for (const unit of state.units.values()) {
    if (unit.dong !== dongName || unit.status !== "info") continue;
    const type = unit.fields["주택형"];
    if (!type || unit.ho.length < 3) continue;
    const line = unit.ho.slice(-2);
    const seen = found.get(line);
    if (seen === undefined) found.set(line, type);
    else if (seen !== type) found.set(line, "혼합");
  }
  return found;
}
```

- [ ] **Step 4: 격자 헤더에 타입 행을 붙인다**

`buildGridTable` 안에서 헤더를 만드는 부분을 찾아, 라인 번호 행 다음에 타입 행을 추가한다.
함수 전체를 아래로 교체한다:

```javascript
function buildGridTable(dong) {
  const table = document.createElement("table");
  table.className = "grid";

  const head = table.insertRow();
  head.append(document.createElement("th"));   // 층 라벨 칸 자리
  dong.grid.lines.forEach((line) => {
    const th = document.createElement("th");
    th.textContent = line;
    head.append(th);
  });

  // 타입 행. 스캔이 끝나야 값이 차므로 자리만 만들어 두고 refreshTypeHeaders 가 채운다.
  const typeRow = table.insertRow();
  typeRow.append(document.createElement("th"));
  dong.grid.lines.forEach((line) => {
    const th = document.createElement("th");
    th.className = "type";
    th.dataset.dong = dong.name;
    th.dataset.line = line;
    typeRow.append(th);
  });

  const byFloor = new Map();
  Object.entries(dong.grid.cells).forEach(([ho, [floor, line]]) => {
    if (!byFloor.has(floor)) byFloor.set(floor, new Map());
    byFloor.get(floor).set(line, ho);
  });
  dong.grid.floors.forEach((floor) => {
    const row = table.insertRow();
    const th = document.createElement("th");
    th.textContent = floor + "F";
    row.append(th);
    dong.grid.lines.forEach((line) => {
      const cell = row.insertCell();
      const ho = byFloor.get(floor)?.get(line);
      if (ho) cell.append(makeCell(dong.name, ho));
    });
  });
  return table;
}

function refreshTypeHeaders() {
  const cache = new Map();
  document.querySelectorAll("th.type").forEach((th) => {
    const dong = th.dataset.dong;
    if (!cache.has(dong)) cache.set(dong, lineTypes(dong));
    const type = cache.get(dong).get(th.dataset.line);
    th.textContent = type ? (type === "혼합" ? "혼합" : shortType(type)) : "";
  });
}
```

- [ ] **Step 5: 스캔이 끝날 때 헤더를 채운다**

`onDone` 의 첫 줄에 `refreshTypeHeaders();` 를 넣는다:

```javascript
function onDone(summary) {
  refreshTypeHeaders();
  renderLegend(summary);
  renderEmptyList();
  renderActions(summary);
}
```

- [ ] **Step 6: 범례에 빈칸 설명을 넣는다**

`renderLegend` 를 아래로 교체한다:

```javascript
function renderLegend(summary) {
  document.querySelectorAll(".legend").forEach((node) => node.remove());
  const legend = document.createElement("div");
  legend.className = "legend";
  legend.innerHTML =
    `<span class="swatch" style="background:var(--info)"></span>정보있음 ${summary.info}` +
    `<span class="swatch" style="background:var(--empty)"></span>정보없음 ${summary.empty}` +
    (summary.error ? `<span class="swatch" style="background:var(--err)"></span>조회실패 ${summary.error}` : "") +
    `<span style="margin-left:14px">빈칸 = 청약홈 미등록 (조합원·임대 등 일반분양 외 물량)</span>` +
    `<span style="margin-left:14px">칸 안의 특·일은 그 세대 당첨자의 청약 유형입니다</span>`;
  el("grids").append(legend);
}
```

- [ ] **Step 7: 화면에서 확인한다**

```bash
python3 app.py
```

`상봉 센트럴`을 스캔한다.

Expected:
- 격자 헤더가 두 줄이다. 위는 `01 02 03 04 05`, 아래는 `84A 84B 84C 84D 84E`
- 회색 칸 안에 `특` 또는 `일` 이 보인다
- 주황 칸에는 글자가 없다
- 칸에 마우스를 올리면 `101동 2801호 · 84A · 일반공급` 같은 툴팁이 뜬다
- 범례에 빈칸 설명이 있다

- [ ] **Step 8: 커밋**

```bash
git add static/index.html
git commit -m "feat: 격자 헤더에 타입, 셀에 공급유형 표기"
```

---

### Task 7: UI — 타입별 현황표와 교차 검증

**Files:**
- Modify: `static/index.html` (`#summary` 컨테이너, CSS, `onDone`, `showDetail`, `renderEmptyList`)

**Interfaces:**
- Consumes: Task 5 의 `shortType`·`netArea`·`fmtArea`, Task 6 의 `lineTypes`, `state.meta.supply`
- Produces: 없음 (최종 화면)

- [ ] **Step 1: 현황표 자리와 CSS 를 넣는다**

`<div id="grids"></div>` **앞에** 컨테이너를 추가한다:

```html
<div id="summary"></div>
```

`<style>` 블록 끝에 규칙을 추가한다:

```css
  #summary { margin: 14px 0 6px; }
  #summary h3 { font-size: 15px; margin: 0 0 6px; }
  table.summary { border-collapse: collapse; font-size: 13px; }
  table.summary th, table.summary td { padding: 4px 12px 4px 0; text-align: right; }
  table.summary th { color: var(--dim); font-weight: 400; }
  table.summary td:first-child, table.summary th:first-child { text-align: left; font-weight: 600; }
  table.summary tr.total td { border-top: 1px solid var(--line); font-weight: 600; }
  .warn { background: #fff4e6; border: 1px solid #ffd8a8; color: #8a5a1b;
          padding: 8px 10px; border-radius: 6px; font-size: 13px; margin-bottom: 8px; }
  @media (prefers-color-scheme: dark) { .warn { background:#3a2c17; border-color:#6b5220; color:#f0c992; } }
  .muted { color: var(--dim); font-size: 12px; font-weight: 400; }
```

- [ ] **Step 2: 타입별 집계 함수를 추가한다**

`lineTypes` 아래에 넣는다:

```javascript
// 세대를 타입별로 모은다. 미계약 세대는 주택형이 없으므로 같은 라인의 타입을 빌려 채운다.
function tallyByType() {
  const byDong = new Map();
  const tally = new Map();   // 주택형 → {scanned, empty}
  for (const unit of state.units.values()) {
    if (!byDong.has(unit.dong)) byDong.set(unit.dong, lineTypes(unit.dong));
    const type =
      unit.fields["주택형"] ||
      (unit.ho.length >= 3 ? byDong.get(unit.dong).get(unit.ho.slice(-2)) : "");
    if (!type || type === "혼합") continue;
    if (!tally.has(type)) tally.set(type, { scanned: 0, empty: 0 });
    const row = tally.get(type);
    row.scanned += 1;
    if (unit.status === "empty") row.empty += 1;
  }
  return tally;
}
```

- [ ] **Step 3: 현황표를 그리는 함수를 추가한다**

`tallyByType` 아래에 넣는다:

```javascript
function renderSummary() {
  const tally = tallyByType();
  if (!tally.size) { el("summary").innerHTML = ""; return; }

  const supply = state.meta?.supply || null;
  const byType = new Map((supply || []).map((s) => [s.type, s]));

  // 공고에는 있는데 스캔에 안 잡힌 타입도 표에 남긴다
  const types = new Set([...tally.keys(), ...byType.keys()]);
  const sorted = [...types].sort((a, b) => {
    const d = parseFloat(netArea(a)) - parseFloat(netArea(b));
    return d !== 0 ? d : shortType(a).localeCompare(shortType(b));
  });

  const warnings = [];
  const rows = sorted.map((type) => {
    const t = tally.get(type) || { scanned: 0, empty: 0 };
    const s = byType.get(type);
    if (s && s.total !== t.scanned) {
      warnings.push(
        `${shortType(type)} 타입: 공고 ${s.total}세대 / 스캔 ${t.scanned}세대`
      );
    }
    const base = s ? s.total : t.scanned;
    const rate = base ? ((t.empty / base) * 100).toFixed(1) + "%" : "-";
    // 공고에 있는 타입은 서버가 계산해 보낸 값을, 스캔에서만 나온 타입은 여기서 계산한다
    const label = s ? s.short : shortType(type);
    const net = s ? s.net_area : netArea(type);
    return `<tr>
      <td>${label}</td>
      <td>${fmtArea(net)}</td>
      <td>${s ? fmtArea(s.area) : "-"}</td>
      <td>${s ? `${s.total} <span class="muted">(${s.general} / ${s.special})</span>` : t.scanned}</td>
      <td>${t.empty}</td>
      <td>${rate}</td>
    </tr>`;
  });

  const totalEmpty = [...tally.values()].reduce((sum, t) => sum + t.empty, 0);
  const totalScanned = [...tally.values()].reduce((sum, t) => sum + t.scanned, 0);
  const totalSupply = supply ? supply.reduce((sum, s) => sum + s.total, 0) : totalScanned;
  const totalGeneral = supply ? supply.reduce((sum, s) => sum + s.general, 0) : 0;
  const totalSpecial = supply ? supply.reduce((sum, s) => sum + s.special, 0) : 0;
  const totalRate = totalSupply ? ((totalEmpty / totalSupply) * 100).toFixed(1) + "%" : "-";

  const warnHtml = warnings.length
    ? `<div class="warn">⚠ ${warnings.join(" · ")} — 라인과 타입의 대응이 단순하지 않은 단지일 수 있어
       타입별 집계가 정확하지 않을 수 있습니다.</div>`
    : "";

  el("summary").innerHTML =
    `<h3>타입별 현황 <span class="muted">${supply ? "공고 기준" : "공고 대조 불가 · 스캔 기준"}</span></h3>` +
    warnHtml +
    `<table class="summary"><thead><tr>
       <th>타입</th><th>전용</th><th>공급</th><th>${supply ? "공고(일반/특별)" : "스캔"}</th>
       <th>미계약 추정</th><th>비율</th>
     </tr></thead><tbody>${rows.join("")}` +
    `<tr class="total"><td>합계</td><td></td><td></td>` +
    `<td>${totalSupply}${supply ? ` <span class="muted">(${totalGeneral} / ${totalSpecial})</span>` : ""}</td>` +
    `<td>${totalEmpty}</td><td>${totalRate}</td></tr></tbody></table>`;
}
```

- [ ] **Step 4: `onDone` 에서 현황표를 그린다**

```javascript
function onDone(summary) {
  refreshTypeHeaders();
  renderSummary();
  renderLegend(summary);
  renderEmptyList();
  renderActions(summary);
}
```

스캔을 새로 시작할 때 이전 표가 남지 않도록, `scan-button` 클릭 핸들러의 `el("grids").innerHTML = "";` 다음 줄에 추가한다:

```javascript
  el("summary").innerHTML = "";
```

- [ ] **Step 5: 정보없음 목록에 타입 컬럼을 넣는다**

`renderEmptyList` 를 아래로 교체한다. 기존 `referenceType` 함수는 `lineTypes` 로 대체되므로 삭제한다:

```javascript
function renderEmptyList() {
  const empties = [...state.units.values()]
    .filter((unit) => unit.status === "empty")
    .sort((a, b) => a.dong.localeCompare(b.dong) || Number(a.ho) - Number(b.ho));

  if (!empties.length) {
    el("empty-list").innerHTML = "<p>정보없음 세대가 없습니다.</p>";
    return;
  }
  const byDong = new Map();
  const rows = empties
    .map((unit) => {
      if (!byDong.has(unit.dong)) byDong.set(unit.dong, lineTypes(unit.dong));
      const type = unit.ho.length >= 3 ? byDong.get(unit.dong).get(unit.ho.slice(-2)) || "" : "";
      const shown = type && type !== "혼합" ? shortType(type) : type;
      return `<tr><td>${unit.dong}</td><td>${unit.ho}</td><td>${shown}</td>` +
             `<td>${type && type !== "혼합" ? fmtArea(netArea(type)) : ""}</td></tr>`;
    })
    .join("");
  el("empty-list").innerHTML =
    `<h3>정보없음 ${empties.length}세대</h3>` +
    `<table class="list"><thead><tr><th>동</th><th>호</th><th>타입(참고)</th><th>전용</th></tr></thead>` +
    `<tbody>${rows}</tbody></table>`;
}
```

- [ ] **Step 6: 미계약 세대 상세에 타입 정보를 붙인다**

`showDetail` 의 `if (unit.status !== "info")` 블록을 아래로 교체한다:

```javascript
  if (unit.status !== "info") {
    if (unit.status !== "empty") {
      el("detail").innerHTML = `<b>${dong}동 ${ho}호</b> — 조회 실패`;
      return;
    }
    const type = unit.ho.length >= 3 ? lineTypes(dong).get(ho.slice(-2)) || "" : "";
    const s = (state.meta?.supply || []).find((x) => x.type === type);
    const parts = [];
    if (type && type !== "혼합") {
      parts.push(`${shortType(type)} · 전용 ${fmtArea(netArea(type))}`);
    }
    if (s) parts.push(`공고 ${s.total}세대 (일반 ${s.general} / 특별 ${s.special})`);
    el("detail").innerHTML =
      `<b>${dong}동 ${ho}호</b> — 정보없음 (미계약·부적격 추정)` +
      (parts.length ? `<div class="muted">${parts.join(" · ")}</div>` : "");
    return;
  }
```

- [ ] **Step 7: 화면에서 확인한다**

```bash
python3 app.py
```

`상봉 센트럴`을 스캔한다.

Expected — 격자 위에 현황표가 나오고 값이 아래와 같다 (2026-07-24 실측):

```
타입별 현황  공고 기준
 타입   전용       공급        공고(일반/특별)   미계약 추정   비율
 84A   84.84㎡   116.95㎡    45 (22 / 23)          2        4.4%
 84B   84.77㎡   118.00㎡    49 (23 / 26)          4        8.2%
 84C   84.67㎡   117.15㎡    51 (23 / 28)          6       11.8%
 84D   84.72㎡   119.48㎡    49 (23 / 26)          2        4.1%
 84E   84.92㎡   118.29㎡    48 (22 / 26)          4        8.3%
 합계                       242 (113 / 129)       18        7.4%
```

- 경고 문구가 **뜨지 않아야** 한다 (공고와 스캔이 타입별로 일치)
- 정보없음 목록에 `타입(참고)` 와 `전용` 컬럼이 있다
- 주황 칸을 클릭하면 `84E · 전용 84.92㎡ · 공고 48세대 (일반 22 / 특별 26)` 가 보인다

- [ ] **Step 8: 커밋**

```bash
git add static/index.html
git commit -m "feat: 타입별 현황표와 공고 교차 검증 추가"
```

---

### Task 8: 문서 갱신과 마무리 검증

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: 전체
- Produces: 없음

- [ ] **Step 1: `README.md` 의 「쓰는 법」 을 갱신한다**

기존 3·4번 항목을 아래로 교체한다:

```markdown
3. **주황색 칸이 정보없음 세대**다. 칸을 누르면 아래에 상세가 뜬다
   - 격자 헤더 아래줄이 타입(`84A`), 칸 안의 `특`/`일` 이 그 세대 당첨자의 청약 유형이다
   - 빈칸은 청약홈에 등록되지 않은 호수다 (조합원·임대 등 일반분양 외 물량)
4. 격자 위 **타입별 현황표**로 어느 타입에 미계약이 몰렸는지 본다
5. 그리드 아래 `정보없음 N세대` 표가 최종 결과다. `CSV로 내려받기`로 저장한다
```

- [ ] **Step 2: 「판정 기준」 아래에 타입·공급유형 설명을 추가한다**

`참고용으로만 쓸 것.` 문단 다음에 넣는다:

```markdown
### 타입과 공급유형

타입(주택형)은 라인(호수 끝 두 자리)마다 고정이라, 미계약 세대의 타입도 같은 라인의 계약 세대에서 알아낼 수 있다.
상봉 센트럴 아이파크에서 이렇게 채운 타입별 세대수가 공고와 정확히 일치하는 것을 확인했다.
혹시 어긋나는 단지가 있으면 현황표 위에 경고가 뜬다.

공급유형(특별/일반)은 **세대의 속성이 아니라 그 세대에 당첨된 사람의 청약 유형**이다.
그래서 미계약 세대에는 값이 없고, 같은 라인 안에서도 층마다 섞인다. 격자에서 미계약 칸이 비어 있는 이유다.
타입 단위 배정 세대수는 공고에서 가져와 현황표에 보여준다.

격자의 빈칸은 청약홈이 호 목록에 넣지 않은 호수다. 조합원분·임대 등 일반분양 대상이 아닌 물량으로 보인다.
상봉의 경우 호 목록 242세대가 공고의 공급규모 242세대와 정확히 같았다.
즉 스캔은 처음부터 특별공급·일반공급 세대 안에서만 이뤄진다.
```

- [ ] **Step 3: 「테스트」 절의 건수를 갱신한다**

`기본 실행은 61건이며 라이브 2건은 건너뛴다.` 를 아래로 바꾼다:

```markdown
기본 실행은 84건이며 라이브 2건은 건너뛴다.
```

- [ ] **Step 4: 전체 테스트를 돌린다**

Run: `python3 -m unittest discover -s tests`
Expected: PASS — 84개, skipped 2 (기존 59 + Task 1 의 6 + Task 2 의 13 + Task 3 의 4 + Task 4 의 2)

- [ ] **Step 5: 라이브 회귀 테스트를 돌린다**

Run: `APPLYHOME_LIVE=1 python3 -m unittest tests.test_live -v`
Expected: PASS — 2개. 상봉 101동 정보없음 10건이 그대로여야 한다

- [ ] **Step 6: 장위로 넓은 단지를 확인한다**

```bash
python3 app.py
```

`장위 푸르지오`를 검색해 스캔한다 (23개 동 1032세대, 약 1분).

Expected:
- 동 23개가 가로로 여러 줄에 걸쳐 배치된다
- 현황표에 18개 타입이 나오고 합계가 `1032 (일반 510 / 특별 522)` 이다
- 타입이 `39A, 39B, 46, 51A, 51C, 59A~59E, 74A, 74B, 84A~84D, 101, 114` 로 표기된다
- 경고가 뜨면 그 타입은 라인·타입 대응이 단순하지 않은 것이다. 값을 기록해 두고 넘어간다

- [ ] **Step 7: 커밋**

```bash
git add README.md
git commit -m "docs: 타입·공급유형 구분 사용법 추가"
```

---

## 완료 기준

- [ ] `python3 -m unittest discover -s tests` 가 86건 통과한다 (라이브 2건 skip)
- [ ] 격자 헤더 아래줄에 타입이, 회색 칸 안에 `특`/`일` 이 표시된다
- [ ] 미계약 칸에는 글자가 없다 (공급유형이 존재하지 않으므로)
- [ ] 격자 위 타입별 현황표가 공고 기준 `일반/특별/계` 와 미계약 수를 보여준다
- [ ] 상봉 스캔 시 교차 검증 경고가 뜨지 않는다
- [ ] 범례에 빈칸(조합원·임대) 설명이 있다
- [ ] 동 블록이 화면 가로 폭에 맞춰 여러 개씩 배치된다
- [ ] CSV 헤더가 `동,호,타입,판정,...` 이다
- [ ] 공고 조회가 실패해도 스캔이 정상 동작하고 현황표가 `공고 대조 불가` 로 뜬다
