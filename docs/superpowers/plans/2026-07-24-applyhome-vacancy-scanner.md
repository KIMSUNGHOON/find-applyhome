# 청약홈 미계약 세대 스캐너 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 청약홈 「분양권 정보(전매제한 등)」 페이지에서 한 단지의 전 동·전 호를 자동으로 훑어, 분양권 정보가 등록되지 않은(= 미계약·부적격 추정) 세대를 한 화면에 보여주는 로컬 웹 도구를 만든다.

**Architecture:** 브라우저(단일 HTML)가 로컬 파이썬 서버(`127.0.0.1:8765`)에 붙고, 서버가 청약홈 내부 API 4종을 프록시한다. 스캔은 서버에서 스레드 4개로 병렬 실행하며 SSE로 세대별 결과를 실시간 전달한다. 파싱 로직은 네트워크와 분리해 저장된 fixture만으로 전부 테스트한다.

**Tech Stack:** Python 3.14 표준 라이브러리만 (`http.server`, `urllib.request`, `concurrent.futures`, `unittest`), 바닐라 JS.

## Global Constraints

- **서드파티 패키지 금지.** 표준 라이브러리만 사용한다. 테스트 러너도 `unittest`를 쓴다.
- 테스트 실행: `python3 -m unittest discover -s tests -v`
- 서버는 `127.0.0.1`에만 바인딩한다. 포트 `8765`.
- 청약홈 호출 규약: 동시 **4** 스레드, 요청 간 **0.1초** 간격, 재시도 **3회**(0.5s → 1s → 2s), 타임아웃 **20초**.
- 고정 헤더: `User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36`, `Referer: https://www.applyhome.co.kr/rs/rsa/selectResaleListView.do`
- **판정 규칙:** 상세 응답에서 `id="houseManageNo"` 요소의 텍스트가 비면 `empty`, 있으면 `info`, 요청 실패면 `error`.
- **라벨 정규화:** 청약홈 라벨에는 각주 기호가 붙는다 (`특이사항 **`, `분양금액(만원)***`). 매칭 전 후행 `*`를 제거한다.
- **동 식별자 2종을 혼동하지 말 것.** `DONG_SN`(예: `1`)은 `selectHoList.do`에, `DONG_NM`(예: `"1001"`)은 `selectResalePblancDetail.do`에 넘긴다.
- UI 결과 영역 상단에는 다음 문구를 항상 노출한다:
  > 이 결과는 청약홈에 분양권 정보가 등록되지 않은 세대입니다. 미계약·부적격 세대일 가능성이 높으나, 사업주체의 등록 지연일 수도 있으므로 참고용으로만 활용하세요.

## 준비된 자산

`tests/fixtures/`에 2026-07-24 실측 응답이 이미 저장되어 있다. 네트워크 없이 Task 1~5를 진행할 수 있다.

| 파일 | 내용 | 실측값 |
|---|---|---|
| `list_seoul_p1.html` | 서울 1페이지 단지 목록 | 총 168건, 행 10개, 첫 행 = 장위 푸르지오 마크원 `2026000275` |
| `donglist_jangwi.json` | 장위 동 목록 | 23개 동, 첫 동 `DONG_SN=1 / DONG_NM="1001"` |
| `holist_jangwi_dong1.json` | 장위 1001동 호 목록 | 18호 |
| `detail_info.html` | 장위 1001동 201호 상세 | `info`, 주택형 `046.8700`, 분양금액 `83,430` |
| `detail_empty.html` | 상봉 센트럴 아이파크 101동 305호 상세 | `empty` |
| `holist_sangbong_dong1.json` | 상봉 101동 호 목록 | 119호 |

## File Structure

| 파일 | 책임 |
|---|---|
| `applyhome.py` | 청약홈 API 4종 호출 + 응답 파싱. 네트워크 계층의 전부이자 유일한 곳 |
| `grid.py` | 호수 문자열 → 층·라인 격자 산출 (순수 함수) |
| `scanner.py` | 단지 1개 전수 스캔. 동시성·간격·중단 제어 |
| `server.py` | HTTP 라우팅, SSE, CSV 생성 |
| `app.py` | 진입점. 서버 기동 + 브라우저 열기 |
| `static/index.html` | UI 전체 |
| `tests/test_*.py` | 파싱·판정·격자·스캔 테스트 |

---

### Task 1: `applyhome.py` — HTTP 계층과 단지 검색

**Files:**
- Create: `applyhome.py`
- Test: `tests/test_parse_list.py`

**Interfaces:**
- Consumes: 없음 (첫 작업)
- Produces: `Complex` 데이터클래스(`house_manage_no`, `pblanc_no`, `name`, `notice_date`, `winner_date`, `resale_limit` — 전부 `str`), `parse_complex_list(html: str) -> tuple[list[Complex], int]`, `search_complexes(name="", area="", sigungu="", page=1) -> tuple[list[Complex], int]`, 내부 헬퍼 `_post(url, data, ajax=False) -> str` / `_text(html) -> str` / `_normalize_label(s) -> str` / `_label_pairs(cells, labels) -> dict[str,str]`, 예외 `ApplyhomeError` / `BlockedError`

- [ ] **Step 1: 저장소 초기화** (이미 git 저장소면 건너뛴다)

```bash
cd /Users/sunghoonk/Workspaces/applyhome
git init
printf '__pycache__/\n*.pyc\n.DS_Store\n' > .gitignore
git add .gitignore docs tests/fixtures
git commit -m "chore: 설계 문서와 청약홈 응답 fixture 추가"
```

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_parse_list.py`:

```python
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import applyhome

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


class ParseComplexListTest(unittest.TestCase):
    def setUp(self):
        self.html = (FIXTURES / "list_seoul_p1.html").read_text(encoding="utf-8")

    def test_총건수를_읽는다(self):
        _, total = applyhome.parse_complex_list(self.html)
        self.assertEqual(total, 168)

    def test_한_페이지에서_단지_10건을_뽑는다(self):
        rows, _ = applyhome.parse_complex_list(self.html)
        self.assertEqual(len(rows), 10)

    def test_첫_단지의_필드가_정확하다(self):
        rows, _ = applyhome.parse_complex_list(self.html)
        first = rows[0]
        self.assertEqual(first.name, "장위 푸르지오 마크원")
        self.assertEqual(first.house_manage_no, "2026000275")
        self.assertEqual(first.pblanc_no, "2026000275")
        self.assertEqual(first.notice_date, "2026.06.19")
        self.assertEqual(first.winner_date, "2026.07.08")
        self.assertIn("특별공급", first.resale_limit)

    def test_모든_단지가_관리번호를_가진다(self):
        rows, _ = applyhome.parse_complex_list(self.html)
        for row in rows:
            self.assertTrue(row.house_manage_no.isdigit(), row.name)
            self.assertTrue(row.name)


class NormalizeLabelTest(unittest.TestCase):
    def test_각주_기호를_제거한다(self):
        self.assertEqual(applyhome._normalize_label("분양금액(만원)***"), "분양금액(만원)")
        self.assertEqual(applyhome._normalize_label("특이사항 **"), "특이사항")
        self.assertEqual(applyhome._normalize_label("추가입주 계약체결일 *"), "추가입주 계약체결일")
        self.assertEqual(applyhome._normalize_label("공고일"), "공고일")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: 테스트를 돌려 실패를 확인한다**

Run: `python3 -m unittest tests.test_parse_list -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'applyhome'`

- [ ] **Step 4: `applyhome.py` 구현**

```python
"""청약홈 「분양권 정보(전매제한 등)」 페이지의 내부 API 클라이언트.

네트워크 호출과 응답 파싱만 담당한다. 스캔 전략과 서버 로직은 여기 두지 않는다.
"""

from __future__ import annotations

import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

BASE = "https://www.applyhome.co.kr"
LIST_URL = f"{BASE}/rs/rsa/selectResaleListView.do"
DONG_URL = f"{BASE}/rs/rsa/selectDongList.do"
HO_URL = f"{BASE}/rs/rsa/selectHoList.do"
DETAIL_URL = f"{BASE}/rs/rsa/selectResalePblancDetail.do"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
TIMEOUT = 20
RETRIES = 3

LIST_LABELS = frozenset({"주택관리번호", "공고일", "당첨자 발표일", "전매제한"})


class ApplyhomeError(Exception):
    """청약홈 호출이 끝내 실패했다."""


class BlockedError(ApplyhomeError):
    """대기열(넷퍼넬)이나 점검 페이지가 돌아왔다. 정상 JSON이 아니다."""


@dataclass(frozen=True)
class Complex:
    house_manage_no: str
    pblanc_no: str
    name: str
    notice_date: str
    winner_date: str
    resale_limit: str


def _post(url: str, data: dict, ajax: bool = False) -> str:
    """지수 백오프로 재시도하며 POST 한다."""
    body = urllib.parse.urlencode(data).encode()
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": LIST_URL,
        "Content-Type": "application/x-www-form-urlencoded",
    }
    if ajax:
        headers["X-Requested-With"] = "XMLHttpRequest"

    last_error = None
    for attempt in range(RETRIES):
        try:
            request = urllib.request.Request(url, body, headers=headers)
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return response.read().decode("utf-8", "replace")
        except (urllib.error.URLError, OSError) as error:
            last_error = error
            if attempt < RETRIES - 1:
                time.sleep(0.5 * (2**attempt))
    raise ApplyhomeError(f"{url} 요청이 {RETRIES}회 모두 실패했습니다: {last_error}")


def _text(fragment: str) -> str:
    """태그를 걷어내고 공백을 정규화한다."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment)).strip()


def _normalize_label(label: str) -> str:
    """라벨 끝에 붙은 각주 기호(*, **, ***)를 떼어낸다."""
    return re.sub(r"\s*\*+\s*$", "", label).strip()


def _cells(html: str) -> list[str]:
    """<td> 내용을 순서대로 텍스트화한다. 빈 칸은 버리지 않는다."""
    return [_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", html, re.S)]


def _label_pairs(cells: list[str], labels: frozenset[str]) -> dict[str, str]:
    """`라벨, 값` 순으로 늘어선 셀 목록에서 라벨 기준으로 값을 뽑는다.

    값이 비어 다음 라벨이 곧바로 오는 경우(예: 추가입주 계약체결일)를 빈 문자열로 처리한다.
    위치 인덱스가 아니라 라벨로 찾으므로 청약홈이 행 순서를 바꿔도 깨지지 않는다.
    """
    pairs: dict[str, str] = {}
    index = 0
    while index < len(cells):
        key = _normalize_label(cells[index])
        if key not in labels:
            index += 1
            continue
        following = cells[index + 1] if index + 1 < len(cells) else ""
        if _normalize_label(following) in labels:
            pairs[key] = ""
            index += 1
        else:
            pairs[key] = following
            index += 2
    return pairs


_ROW_RE = re.compile(
    r'<div class="aptRow"\s+data-pbno="(?P<pb>\d+)"'
    r'\s+data-hmno="(?P<hm>\d+)"'
    r'\s+data-honm="(?P<nm>[^"]*)"'
)


def parse_complex_list(html: str) -> tuple[list[Complex], int]:
    """단지 목록 HTML에서 (단지 목록, 총건수)를 뽑는다."""
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)

    total = 0
    total_match = re.search(r"총게시물\s*:\s*<b[^>]*>(\d+)</b>", html)
    if total_match:
        total = int(total_match.group(1))

    matches = list(_ROW_RE.finditer(html))
    complexes = []
    for position, match in enumerate(matches):
        end = matches[position + 1].start() if position + 1 < len(matches) else len(html)
        block = html[match.start() : end]
        cells = [c for c in _cells(block) if c]
        pairs = _label_pairs(cells, LIST_LABELS)
        complexes.append(
            Complex(
                house_manage_no=match.group("hm"),
                pblanc_no=match.group("pb"),
                name=match.group("nm"),
                notice_date=pairs.get("공고일", ""),
                winner_date=pairs.get("당첨자 발표일", ""),
                resale_limit=pairs.get("전매제한", ""),
            )
        )
    return complexes, total


def search_complexes(
    name: str = "", area: str = "", sigungu: str = "", page: int = 1
) -> tuple[list[Complex], int]:
    """단지명·지역으로 검색한다. 페이지당 10건."""
    html = _post(
        LIST_URL,
        {
            "suplyAreaCode": area,
            "siggList": sigungu,
            "houseNm": name,
            "pageIndex": str(page),
        },
    )
    return parse_complex_list(html)
```

- [ ] **Step 5: 테스트를 돌려 통과를 확인한다**

Run: `python3 -m unittest tests.test_parse_list -v`
Expected: PASS — 5개 테스트 전부 ok

- [ ] **Step 6: 커밋**

```bash
git add applyhome.py tests/test_parse_list.py
git commit -m "feat: 청약홈 단지 검색 API 클라이언트와 목록 파서 추가"
```

---

### Task 2: `applyhome.py` — 동·호 목록

**Files:**
- Modify: `applyhome.py` (`Complex` 정의 아래에 데이터클래스 추가, 파일 끝에 함수 추가)
- Test: `tests/test_parse_dongho.py`

**Interfaces:**
- Consumes: Task 1의 `_post`, `BlockedError`
- Produces: `Dong(sn: int, name: str)`, `Ho(sn: int, no: str)`, `parse_dong_list(raw: str) -> list[Dong]`, `parse_ho_list(raw: str) -> list[Ho]`, `list_dongs(hm: str, pb: str) -> list[Dong]`, `list_hos(hm: str, pb: str, dong_sn: int) -> list[Ho]`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_parse_dongho.py`:

```python
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import applyhome

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


class ParseDongListTest(unittest.TestCase):
    def test_동_23개를_뽑는다(self):
        raw = (FIXTURES / "donglist_jangwi.json").read_text(encoding="utf-8")
        dongs = applyhome.parse_dong_list(raw)
        self.assertEqual(len(dongs), 23)

    def test_첫_동은_sn과_name이_다르다(self):
        raw = (FIXTURES / "donglist_jangwi.json").read_text(encoding="utf-8")
        first = applyhome.parse_dong_list(raw)[0]
        self.assertEqual(first.sn, 1)
        self.assertEqual(first.name, "1001")

    def test_JSON이_아니면_BlockedError(self):
        with self.assertRaises(applyhome.BlockedError):
            applyhome.parse_dong_list("<html>대기열 안내</html>")


class ParseHoListTest(unittest.TestCase):
    def test_장위_1001동은_18호(self):
        raw = (FIXTURES / "holist_jangwi_dong1.json").read_text(encoding="utf-8")
        self.assertEqual(len(applyhome.parse_ho_list(raw)), 18)

    def test_상봉_101동은_119호(self):
        raw = (FIXTURES / "holist_sangbong_dong1.json").read_text(encoding="utf-8")
        self.assertEqual(len(applyhome.parse_ho_list(raw)), 119)

    def test_호수는_문자열로_변환된다(self):
        raw = (FIXTURES / "holist_jangwi_dong1.json").read_text(encoding="utf-8")
        first = applyhome.parse_ho_list(raw)[0]
        self.assertIsInstance(first.no, str)
        self.assertEqual(first.no, "201")

    def test_JSON이_아니면_BlockedError(self):
        with self.assertRaises(applyhome.BlockedError):
            applyhome.parse_ho_list("서비스 점검 중입니다")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 테스트를 돌려 실패를 확인한다**

Run: `python3 -m unittest tests.test_parse_dongho -v`
Expected: FAIL — `AttributeError: module 'applyhome' has no attribute 'parse_dong_list'`

- [ ] **Step 3: 구현 추가**

`applyhome.py` 상단 import에 `import json`을 추가하고, `Complex` 아래에 데이터클래스를 넣는다:

```python
@dataclass(frozen=True)
class Dong:
    sn: int      # DONG_SN — selectHoList.do 에 넘긴다
    name: str    # DONG_NM — selectResalePblancDetail.do 에 넘긴다


@dataclass(frozen=True)
class Ho:
    sn: int
    no: str
```

파일 끝에 함수를 추가한다:

```python
def _load_json(raw: str, what: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        raise BlockedError(
            f"{what} 응답이 JSON이 아닙니다. 접속 대기열이거나 점검 중일 수 있습니다."
        ) from error


def parse_dong_list(raw: str) -> list[Dong]:
    data = _load_json(raw, "동 목록")
    return [
        Dong(sn=int(item["DONG_SN"]), name=str(item["DONG_NM"]))
        for item in data.get("donglist", [])
    ]


def parse_ho_list(raw: str) -> list[Ho]:
    data = _load_json(raw, "호 목록")
    return [
        Ho(sn=int(item["HO_SN"]), no=str(item["HO_CO"]))
        for item in data.get("holist", [])
    ]


def list_dongs(hm: str, pb: str) -> list[Dong]:
    raw = _post(DONG_URL, {"houseManageNo": hm, "pblancNo": pb}, ajax=True)
    return parse_dong_list(raw)


def list_hos(hm: str, pb: str, dong_sn: int) -> list[Ho]:
    raw = _post(
        HO_URL,
        {"houseManageNo": hm, "pblancNo": pb, "dongsn": str(dong_sn)},
        ajax=True,
    )
    return parse_ho_list(raw)
```

- [ ] **Step 4: 테스트를 돌려 통과를 확인한다**

Run: `python3 -m unittest tests.test_parse_dongho -v`
Expected: PASS — 7개 테스트 전부 ok

- [ ] **Step 5: 커밋**

```bash
git add applyhome.py tests/test_parse_dongho.py
git commit -m "feat: 동·호 목록 조회와 대기열 응답 감지 추가"
```

---

### Task 3: `applyhome.py` — 상세 조회와 정보없음 판정

이 도구의 핵심이다. 청약홈이 경고창을 띄우는 조건과 똑같이 판정한다.

**Files:**
- Modify: `applyhome.py` (파일 끝에 추가)
- Test: `tests/test_parse_detail.py`

**Interfaces:**
- Consumes: Task 1의 `_post`, `_cells`, `_label_pairs`
- Produces: `UnitDetail(dong: str, ho: str, status: str, fields: dict[str, str])` — `status`는 `"info"` / `"empty"` / `"error"` 중 하나, `DETAIL_LABELS: tuple[str, ...]`, `parse_detail(html: str, dong: str, ho: str) -> UnitDetail`, `fetch_detail(hm: str, pb: str, dong_name: str, ho_no: str) -> UnitDetail`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_parse_detail.py`:

```python
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import applyhome

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


class ParseDetailInfoTest(unittest.TestCase):
    def setUp(self):
        html = (FIXTURES / "detail_info.html").read_text(encoding="utf-8")
        self.unit = applyhome.parse_detail(html, "1001", "201")

    def test_정보가_있으면_info로_판정한다(self):
        self.assertEqual(self.unit.status, "info")

    def test_동호는_인자로_받은_값을_유지한다(self):
        self.assertEqual(self.unit.dong, "1001")
        self.assertEqual(self.unit.ho, "201")

    def test_주요_필드값이_정확하다(self):
        fields = self.unit.fields
        self.assertEqual(fields["주택명"], "장위 푸르지오 마크원")
        self.assertEqual(fields["주택형"], "046.8700")
        self.assertEqual(fields["공고일"], "2026.06.19")
        self.assertEqual(fields["당첨자 발표일"], "2026.07.08")
        self.assertEqual(fields["계약체결일"], "2026.07.20 ~ 2026.07.23")
        self.assertEqual(fields["입주예정"], "2030.09")
        self.assertEqual(fields["공급유형"], "특별공급")
        self.assertEqual(fields["지역"], "서울")

    def test_각주가_붙은_라벨도_정규화된_키로_담긴다(self):
        fields = self.unit.fields
        self.assertEqual(fields["분양금액(만원)"], "83,430")
        self.assertEqual(fields["특이사항"], "투기과열지구, 청약과열지역, 정비사업, 과밀억제권역")
        self.assertEqual(fields["전매제한"], "3년(기간내 소유권이전등기시 해제)")

    def test_값이_빈_항목은_빈_문자열이_된다(self):
        self.assertEqual(self.unit.fields["추가입주 계약체결일"], "")

    def test_다음_라벨을_값으로_잘못_당겨오지_않는다(self):
        self.assertNotEqual(self.unit.fields["추가입주 계약체결일"], "입주예정")


class ParseDetailEmptyTest(unittest.TestCase):
    def test_정보가_없으면_empty로_판정한다(self):
        html = (FIXTURES / "detail_empty.html").read_text(encoding="utf-8")
        unit = applyhome.parse_detail(html, "101", "305")
        self.assertEqual(unit.status, "empty")
        self.assertEqual(unit.fields, {})

    def test_houseManageNo_태그가_아예_없어도_empty다(self):
        unit = applyhome.parse_detail("<html><body>오류</body></html>", "101", "305")
        self.assertEqual(unit.status, "empty")


class LabelOrderResilienceTest(unittest.TestCase):
    def test_행_순서가_바뀌어도_값이_정확히_매핑된다(self):
        html = """
        <div id="houseManageNo">2026000275</div>
        <table><tbody>
          <tr><td>공급유형</td><td>일반공급</td></tr>
          <tr><td>주택형</td><td>084.9721</td></tr>
          <tr><td>분양금액(만원)***</td><td>99,000</td></tr>
          <tr><td>주택명</td><td>테스트단지</td></tr>
        </tbody></table>
        """
        unit = applyhome.parse_detail(html, "101", "1502")
        self.assertEqual(unit.status, "info")
        self.assertEqual(unit.fields["공급유형"], "일반공급")
        self.assertEqual(unit.fields["주택형"], "084.9721")
        self.assertEqual(unit.fields["분양금액(만원)"], "99,000")
        self.assertEqual(unit.fields["주택명"], "테스트단지")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 테스트를 돌려 실패를 확인한다**

Run: `python3 -m unittest tests.test_parse_detail -v`
Expected: FAIL — `AttributeError: module 'applyhome' has no attribute 'parse_detail'`

- [ ] **Step 3: 구현 추가**

`applyhome.py` 파일 끝에 추가한다:

```python
DETAIL_LABELS = (
    "주택관리번호",
    "주택명",
    "주택형",
    "공고일",
    "동수",
    "호수",
    "당첨자 발표일",
    "계약체결일",
    "추가입주 계약체결일",
    "입주예정",
    "공급유형",
    "지역",
    "특이사항",
    "전매제한",
    "분양금액(만원)",
)
_DETAIL_LABEL_SET = frozenset(DETAIL_LABELS)

_HOUSE_NO_RE = re.compile(r'id="houseManageNo"[^>]*>(.*?)<', re.S)


@dataclass(frozen=True)
class UnitDetail:
    dong: str
    ho: str
    status: str          # "info" | "empty" | "error"
    fields: dict[str, str]


def parse_detail(html: str, dong: str, ho: str) -> UnitDetail:
    """상세 팝업 HTML을 판정한다.

    청약홈 스크립트는 id="houseManageNo" 의 텍스트가 비면
    "분양권 세부 정보가 없습니다" 경고창을 띄운다. 같은 조건을 그대로 쓴다.
    """
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)

    match = _HOUSE_NO_RE.search(html)
    if match is None or not match.group(1).strip():
        return UnitDetail(dong=dong, ho=ho, status="empty", fields={})

    cells = [c for c in _cells(html) if c]
    return UnitDetail(
        dong=dong,
        ho=ho,
        status="info",
        fields=_label_pairs(cells, _DETAIL_LABEL_SET),
    )


def fetch_detail(hm: str, pb: str, dong_name: str, ho_no: str) -> UnitDetail:
    """한 세대의 분양권 정보를 조회한다. dong_name 은 DONG_NM 이다."""
    html = _post(
        DETAIL_URL,
        {
            "houseManageNo": hm,
            "pblancNo": pb,
            "dongNo": dong_name,
            "hoNo": ho_no,
        },
    )
    return parse_detail(html, dong_name, ho_no)
```

- [ ] **Step 4: 테스트를 돌려 통과를 확인한다**

Run: `python3 -m unittest tests.test_parse_detail -v`
Expected: PASS — 9개 테스트 전부 ok

- [ ] **Step 5: 전체 테스트를 돌려 회귀가 없는지 본다**

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS — 21개 테스트 ok (test_parse_list 5 + test_parse_dongho 7 + test_parse_detail 9)

- [ ] **Step 6: 커밋**

```bash
git add applyhome.py tests/test_parse_detail.py
git commit -m "feat: 세대 상세 조회와 정보없음 판정 추가"
```

---

### Task 4: `grid.py` — 층·라인 격자 산출

**Files:**
- Create: `grid.py`
- Test: `tests/test_grid.py`

**Interfaces:**
- Consumes: 없음 (순수 함수, 다른 모듈에 의존하지 않는다)
- Produces: `build_grid(ho_numbers: list[str]) -> dict | None` — 성공 시 `{"floors": list[int] (내림차순), "lines": list[str] (오름차순), "cells": dict[str, list]}` 형태이며 `cells`는 `{호수: [층(int), 라인(str)]}`. 격자화 불가하면 `None`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_grid.py`:

```python
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import grid


class BuildGridTest(unittest.TestCase):
    def test_마지막_두자리가_라인이고_그_앞이_층이다(self):
        result = grid.build_grid(["201", "305", "1105"])
        self.assertEqual(result["cells"]["201"], [2, "01"])
        self.assertEqual(result["cells"]["305"], [3, "05"])
        self.assertEqual(result["cells"]["1105"], [11, "05"])

    def test_층은_내림차순_라인은_오름차순이다(self):
        result = grid.build_grid(["201", "305", "1105"])
        self.assertEqual(result["floors"], [11, 3, 2])
        self.assertEqual(result["lines"], ["01", "05"])

    def test_같은_층의_여러_라인을_모두_담는다(self):
        result = grid.build_grid(["301", "302", "303"])
        self.assertEqual(result["floors"], [3])
        self.assertEqual(result["lines"], ["01", "02", "03"])

    def test_세자리_미만이_섞이면_격자를_포기한다(self):
        self.assertIsNone(grid.build_grid(["1", "305"]))

    def test_숫자가_아닌_호수가_섞이면_격자를_포기한다(self):
        self.assertIsNone(grid.build_grid(["A2", "305"]))

    def test_빈_목록은_격자를_포기한다(self):
        self.assertIsNone(grid.build_grid([]))

    def test_상봉_101동_119호가_격자화된다(self):
        import json

        raw = json.loads(
            (pathlib.Path(__file__).parent / "fixtures" / "holist_sangbong_dong1.json")
            .read_text(encoding="utf-8")
        )
        hos = [str(item["HO_CO"]) for item in raw["holist"]]
        result = grid.build_grid(hos)
        self.assertIsNotNone(result)
        self.assertEqual(len(result["cells"]), 119)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 테스트를 돌려 실패를 확인한다**

Run: `python3 -m unittest tests.test_grid -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'grid'`

- [ ] **Step 3: `grid.py` 구현**

```python
"""호수 문자열을 층·라인 격자로 배치한다.

호수 마지막 두 자리가 라인, 그 앞이 층이다. "1105" → 11층 05라인.
이 규칙에 맞지 않는 호수가 하나라도 섞이면 격자를 포기하고 None을 돌려준다.
호출한 쪽은 None을 받으면 단순 나열로 표시한다.
"""

from __future__ import annotations


def build_grid(ho_numbers: list[str]) -> dict | None:
    if not ho_numbers:
        return None

    cells: dict[str, list] = {}
    floors: set[int] = set()
    lines: set[str] = set()

    for ho in ho_numbers:
        if len(ho) < 3 or not ho.isdigit():
            return None
        floor = int(ho[:-2])
        line = ho[-2:]
        cells[ho] = [floor, line]
        floors.add(floor)
        lines.add(line)

    return {
        "floors": sorted(floors, reverse=True),
        "lines": sorted(lines),
        "cells": cells,
    }
```

- [ ] **Step 4: 테스트를 돌려 통과를 확인한다**

Run: `python3 -m unittest tests.test_grid -v`
Expected: PASS — 7개 테스트 전부 ok

- [ ] **Step 5: 커밋**

```bash
git add grid.py tests/test_grid.py
git commit -m "feat: 호수를 층·라인 격자로 배치하는 유틸 추가"
```

---

### Task 5: `scanner.py` — 단지 전수 스캔

**Files:**
- Create: `scanner.py`
- Test: `tests/test_scanner.py`

**Interfaces:**
- Consumes: Task 1~3의 `applyhome` 모듈 (`list_dongs`, `list_hos`, `fetch_detail`, `UnitDetail`, `BlockedError`, `ApplyhomeError`), Task 4의 `grid.build_grid`
- Produces: `scan_complex(hm, pb, on_event, stop=None, client=applyhome, max_workers=4, delay=0.1) -> None`. `on_event(name: str, payload: dict)`를 `"meta"` → `"unit"`/`"progress"` 반복 → `"done"` 순으로 호출하며, 실패 시 `"error"`를 호출하고 끝낸다. `client`와 `stop`은 테스트에서 주입한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_scanner.py`:

```python
import pathlib
import sys
import threading
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import applyhome
import scanner


class FakeClient:
    """네트워크 없이 scanner 를 돌리기 위한 대역."""

    BlockedError = applyhome.BlockedError
    ApplyhomeError = applyhome.ApplyhomeError
    UnitDetail = applyhome.UnitDetail

    def __init__(self, dongs, hos, empty_hos=(), error_hos=()):
        self._dongs = dongs
        self._hos = hos
        self._empty = set(empty_hos)
        self._error = set(error_hos)

    def list_dongs(self, hm, pb):
        return self._dongs

    def list_hos(self, hm, pb, dong_sn):
        return self._hos[dong_sn]

    def fetch_detail(self, hm, pb, dong_name, ho_no):
        if (dong_name, ho_no) in self._error:
            raise applyhome.ApplyhomeError("일부러 낸 실패")
        if (dong_name, ho_no) in self._empty:
            return applyhome.UnitDetail(dong_name, ho_no, "empty", {})
        return applyhome.UnitDetail(dong_name, ho_no, "info", {"주택형": "084.9721"})


def collect(client, **kwargs):
    events = []
    scanner.scan_complex(
        "1", "1", lambda name, payload: events.append((name, payload)),
        client=client, delay=0, **kwargs
    )
    return events


class ScanComplexTest(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient(
            dongs=[applyhome.Dong(1, "101")],
            hos={1: [applyhome.Ho(1, "201"), applyhome.Ho(2, "202"), applyhome.Ho(3, "301")]},
            empty_hos={("101", "202")},
        )

    def test_meta가_가장_먼저_나온다(self):
        events = collect(self.client)
        self.assertEqual(events[0][0], "meta")
        self.assertEqual(events[0][1]["total"], 3)

    def test_meta에_동별_호목록과_격자가_들어있다(self):
        events = collect(self.client)
        dong = events[0][1]["dongs"][0]
        self.assertEqual(dong["name"], "101")
        self.assertEqual(dong["hos"], ["201", "202", "301"])
        self.assertEqual(dong["grid"]["cells"]["301"], [3, "01"])

    def test_done이_마지막이며_집계가_맞다(self):
        events = collect(self.client)
        name, payload = events[-1]
        self.assertEqual(name, "done")
        self.assertEqual(payload["total"], 3)
        self.assertEqual(payload["info"], 2)
        self.assertEqual(payload["empty"], 1)
        self.assertEqual(payload["error"], 0)

    def test_세대마다_unit_이벤트가_한번씩_나온다(self):
        events = collect(self.client)
        units = [payload for name, payload in events if name == "unit"]
        self.assertEqual(len(units), 3)
        self.assertEqual({u["ho"] for u in units}, {"201", "202", "301"})

    def test_empty_세대가_표시된다(self):
        events = collect(self.client)
        empties = [p for n, p in events if n == "unit" and p["status"] == "empty"]
        self.assertEqual(len(empties), 1)
        self.assertEqual(empties[0]["ho"], "202")

    def test_조회_실패는_error_상태로_담기고_스캔은_계속된다(self):
        client = FakeClient(
            dongs=[applyhome.Dong(1, "101")],
            hos={1: [applyhome.Ho(1, "201"), applyhome.Ho(2, "202")]},
            error_hos={("101", "202")},
        )
        events = collect(client)
        self.assertEqual(events[-1][0], "done")
        self.assertEqual(events[-1][1]["error"], 1)
        self.assertEqual(events[-1][1]["info"], 1)


class ScanFailureTest(unittest.TestCase):
    def test_동목록이_비면_error를_내고_끝낸다(self):
        client = FakeClient(dongs=[], hos={})
        events = collect(client)
        self.assertEqual(events[0][0], "error")
        self.assertIn("등록", events[0][1]["message"])

    def test_대기열이면_error를_낸다(self):
        class Blocked(FakeClient):
            def list_dongs(self, hm, pb):
                raise applyhome.BlockedError("대기열입니다")

        events = collect(Blocked(dongs=[], hos={}))
        self.assertEqual(events[0][0], "error")
        self.assertIn("대기열", events[0][1]["message"])


class StopTest(unittest.TestCase):
    def test_stop이_설정되면_done을_내지_않고_멈춘다(self):
        stop = threading.Event()
        stop.set()
        client = FakeClient(
            dongs=[applyhome.Dong(1, "101")],
            hos={1: [applyhome.Ho(1, "201")]},
        )
        events = collect(client, stop=stop)
        self.assertNotIn("done", [name for name, _ in events])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 테스트를 돌려 실패를 확인한다**

Run: `python3 -m unittest tests.test_scanner -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scanner'`

- [ ] **Step 3: `scanner.py` 구현**

```python
"""단지 하나의 전 동·전 호를 훑는다.

청약홈이 공공 사이트인 점을 감안해 동시 요청 수와 간격을 보수적으로 잡았다.
결과는 on_event 콜백으로 흘려보내며, 이 모듈은 HTTP 서버를 알지 못한다.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import applyhome
import grid

PROGRESS_EVERY = 10


def scan_complex(
    hm: str,
    pb: str,
    on_event: Callable[[str, dict], None],
    stop: threading.Event | None = None,
    client=applyhome,
    max_workers: int = 4,
    delay: float = 0.1,
) -> None:
    stop = stop or threading.Event()
    started = time.monotonic()

    try:
        dongs = client.list_dongs(hm, pb)
    except applyhome.ApplyhomeError as error:
        on_event("error", {"message": str(error)})
        return

    if not dongs:
        on_event("error", {"message": "이 단지는 아직 분양권 정보가 등록되지 않았습니다."})
        return

    jobs: list[tuple[str, str]] = []
    meta_dongs = []
    for dong in dongs:
        if stop.is_set():
            return
        try:
            hos = client.list_hos(hm, pb, dong.sn)
        except applyhome.ApplyhomeError as error:
            on_event("error", {"message": str(error)})
            return
        ho_numbers = [ho.no for ho in hos]
        meta_dongs.append(
            {"name": dong.name, "hos": ho_numbers, "grid": grid.build_grid(ho_numbers)}
        )
        jobs.extend((dong.name, ho) for ho in ho_numbers)

    if not jobs:
        on_event("error", {"message": "이 단지는 아직 분양권 정보가 등록되지 않았습니다."})
        return

    on_event("meta", {"total": len(jobs), "dongs": meta_dongs})

    tally = {"info": 0, "empty": 0, "error": 0}
    done_count = 0
    lock = threading.Lock()

    def work(job: tuple[str, str]) -> dict:
        dong_name, ho_no = job
        if stop.is_set():
            return {"dong": dong_name, "ho": ho_no, "status": "error", "fields": {}}
        if delay:
            time.sleep(delay)
        try:
            unit = client.fetch_detail(hm, pb, dong_name, ho_no)
            return {
                "dong": unit.dong,
                "ho": unit.ho,
                "status": unit.status,
                "fields": unit.fields,
            }
        except applyhome.ApplyhomeError:
            return {"dong": dong_name, "ho": ho_no, "status": "error", "fields": {}}

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for result in pool.map(work, jobs):
            if stop.is_set():
                return
            with lock:
                tally[result["status"]] = tally.get(result["status"], 0) + 1
                done_count += 1
                current = done_count
            on_event("unit", result)
            if current % PROGRESS_EVERY == 0:
                on_event("progress", {"done": current, "total": len(jobs)})

    if stop.is_set():
        return

    on_event(
        "done",
        {
            "total": len(jobs),
            "info": tally["info"],
            "empty": tally["empty"],
            "error": tally["error"],
            "elapsed": round(time.monotonic() - started, 1),
        },
    )
```

- [ ] **Step 4: 테스트를 돌려 통과를 확인한다**

Run: `python3 -m unittest tests.test_scanner -v`
Expected: PASS — 9개 테스트 전부 ok

- [ ] **Step 5: 전체 테스트 확인**

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS — 37개 테스트 ok (앞선 21 + test_grid 7 + test_scanner 9)

- [ ] **Step 6: 커밋**

```bash
git add scanner.py tests/test_scanner.py
git commit -m "feat: 단지 전수 스캔 엔진 추가"
```

---

### Task 6: `server.py` — 라우팅과 단지 검색 API

**Files:**
- Create: `server.py`
- Create: `static/index.html` (자리만 잡는 최소 파일. Task 9에서 본격 작성한다)
- Test: `tests/test_server_search.py`

**Interfaces:**
- Consumes: Task 1의 `applyhome.search_complexes`, `applyhome.Complex`
- Produces: `Handler` (`http.server.BaseHTTPRequestHandler` 상속), `serve(port: int = 8765) -> None`, `complex_to_dict(c: applyhome.Complex) -> dict`, 모듈 전역 `SCANS: dict[str, list[dict]]`
- `GET /api/search?name=&area=&sigungu=&page=` → `{"complexes": [...], "total": int}`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_server_search.py`:

```python
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
        applyhome.search_complexes = lambda name="", area="", sigungu="", page=1: (
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
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        applyhome.search_complexes = cls.original

    def get(self, path):
        url = f"http://127.0.0.1:{self.port}{path}"
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

    def test_한글_검색어가_깨지지_않는다(self):
        status, _ = self.get("/api/search?name=%EC%83%81%EB%B4%89")
        self.assertEqual(status, 200)

    def test_없는_경로는_404다(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.get("/api/nope")
        self.assertEqual(caught.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 테스트를 돌려 실패를 확인한다**

Run: `python3 -m unittest tests.test_server_search -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'server'`

- [ ] **Step 3: `static/index.html` 자리잡기**

```html
<!doctype html>
<meta charset="utf-8">
<title>청약홈 미계약 세대 스캐너</title>
<p>준비 중</p>
```

- [ ] **Step 4: `server.py` 구현**

```python
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
```

- [ ] **Step 5: 테스트를 돌려 통과를 확인한다**

Run: `python3 -m unittest tests.test_server_search -v`
Expected: PASS — 4개 테스트 전부 ok

- [ ] **Step 6: 커밋**

```bash
git add server.py static/index.html tests/test_server_search.py
git commit -m "feat: 로컬 서버와 단지 검색 API 추가"
```

---

### Task 7: `server.py` — 스캔 SSE 스트림

**Files:**
- Modify: `server.py` (`do_GET` 분기에 `/api/scan` 추가, `_handle_scan` 메서드 추가)
- Test: `tests/test_server_scan.py`

**Interfaces:**
- Consumes: Task 5의 `scanner.scan_complex`, Task 6의 `Handler`·`SCANS`
- Produces: `GET /api/scan?hm=&pb=` → `text/event-stream`. 이벤트는 `meta` / `unit` / `progress` / `done` / `error`. `done` 페이로드에 `token`이 실리며 그 토큰으로 `SCANS`에서 결과를 꺼낼 수 있다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_server_scan.py`:

```python
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
```

- [ ] **Step 2: 테스트를 돌려 실패를 확인한다**

Run: `python3 -m unittest tests.test_server_scan -v`
Expected: FAIL — `/api/scan`이 404를 돌려주어 `HTTPError: 404`

- [ ] **Step 3: `server.py` 수정**

상단 import에 다음을 추가한다:

```python
import secrets
import threading

import scanner
```

`do_GET`의 분기에 한 줄을 끼운다 (`/api/search` 분기 바로 아래):

```python
        elif parsed.path == "/api/scan":
            self._handle_scan(query)
```

`_handle_search` 아래에 메서드를 추가한다:

```python
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
```

- [ ] **Step 4: 테스트를 돌려 통과를 확인한다**

Run: `python3 -m unittest tests.test_server_scan -v`
Expected: PASS — 5개 테스트 전부 ok

- [ ] **Step 5: 커밋**

```bash
git add server.py tests/test_server_scan.py
git commit -m "feat: 스캔 진행 상황을 SSE로 스트리밍"
```

---

### Task 8: `server.py` — CSV 내보내기와 세대 재조회

**Files:**
- Modify: `server.py` (`do_GET` 분기에 `/api/export`·`/api/unit` 추가, `build_csv`·`_handle_export`·`_handle_unit` 추가)
- Test: `tests/test_export.py`

**Interfaces:**
- Consumes: Task 7의 `SCANS`, Task 3의 `applyhome.fetch_detail`
- Produces: `build_csv(units: list[dict]) -> str` — UTF-8 BOM으로 시작하는 CSV 문자열.
  `GET /api/export?token=` → `text/csv` 다운로드.
  `GET /api/unit?hm=&pb=&dong=&ho=` → 세대 하나를 다시 조회해 `{"dong","ho","status","fields"}` JSON 반환 (Task 10의 실패 재시도 버튼이 쓴다)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_export.py`:

```python
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
            "주택형": "084.9721",
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
            "동,호,판정,주택형,공급유형,공고일,당첨자 발표일,계약체결일,입주예정,전매제한,분양금액(만원)",
        )

    def test_세대수만큼_행이_나온다(self):
        lines = server.build_csv(UNITS).lstrip("﻿").strip().splitlines()
        self.assertEqual(len(lines), 4)  # 헤더 1 + 세대 3

    def test_판정을_한글로_적는다(self):
        lines = server.build_csv(UNITS).lstrip("﻿").strip().splitlines()
        self.assertIn("정보있음", lines[1])
        self.assertIn("정보없음", lines[2])
        self.assertIn("조회실패", lines[3])

    def test_정보없음_행은_상세칸이_비어있다(self):
        lines = server.build_csv(UNITS).lstrip("﻿").strip().splitlines()
        self.assertEqual(lines[2], "101,305,정보없음,,,,,,,,")

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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 테스트를 돌려 실패를 확인한다**

Run: `python3 -m unittest tests.test_export -v`
Expected: FAIL — `AttributeError: module 'server' has no attribute 'build_csv'`

- [ ] **Step 3: `server.py` 수정**

상단 import에 `import csv`, `import io`를 추가한다.

`complex_to_dict` 아래에 추가한다:

```python
CSV_HEADER = (
    "동", "호", "판정", "주택형", "공급유형", "공고일",
    "당첨자 발표일", "계약체결일", "입주예정", "전매제한", "분양금액(만원)",
)
STATUS_LABEL = {"info": "정보있음", "empty": "정보없음", "error": "조회실패"}


def build_csv(units: list[dict]) -> str:
    """엑셀에서 바로 열리도록 UTF-8 BOM을 붙인 CSV 를 만든다."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_HEADER)
    for unit in units:
        fields = unit.get("fields") or {}
        writer.writerow(
            [
                unit.get("dong", ""),
                unit.get("ho", ""),
                STATUS_LABEL.get(unit.get("status", ""), unit.get("status", "")),
                *(fields.get(key, "") for key in CSV_HEADER[3:]),
            ]
        )
    return "﻿" + buffer.getvalue()
```

`do_GET` 분기에 추가한다 (`/api/scan` 바로 아래):

```python
        elif parsed.path == "/api/export":
            self._handle_export(query)
        elif parsed.path == "/api/unit":
            self._handle_unit(query)
```

`_handle_scan` 아래에 메서드 두 개를 추가한다:

```python
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
```

- [ ] **Step 4: 테스트를 돌려 통과를 확인한다**

Run: `python3 -m unittest tests.test_export -v`
Expected: PASS — 8개 테스트 전부 ok

- [ ] **Step 5: 전체 테스트 확인**

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS — 54개 테스트 ok (앞선 37 + test_server_search 4 + test_server_scan 5 + test_export 8)

- [ ] **Step 6: 커밋**

```bash
git add server.py tests/test_export.py
git commit -m "feat: 스캔 결과 CSV 내보내기 추가"
```

---

### Task 9: `static/index.html` — 검색과 스캔 진행

**Files:**
- Modify: `static/index.html` (전체 교체)
- Create: `app.py`

**Interfaces:**
- Consumes: `GET /api/search`, `GET /api/scan` (SSE)
- Produces: 화면 요소 `#search-form`, `#q`, `#area`, `#results`, `#search-status`, `#more`, `#scan-button`, `#stop-button`, `#progress`, `#notice`, `#grids`, `#empty-list`.
  전역 상태 `state = {complex, meta, units: Map, token, source, search: {name, area, page, loaded, total}}`,
  헬퍼 `el(id)`, 빈 자리 함수 `onMeta(meta)` / `onUnit(unit)` / `onDone(summary)` — Task 10이 이 상태를 읽어 그리고 세 함수를 채운다.

- [ ] **Step 1: `app.py` 작성**

```python
"""청약홈 미계약 세대 스캐너 진입점."""

import threading
import webbrowser

import server

PORT = 8765

if __name__ == "__main__":
    threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()
    server.serve(PORT)
```

- [ ] **Step 2: `static/index.html` 작성 (검색 + 진행률까지)**

```html
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>청약홈 미계약 세대 스캐너</title>
<style>
  :root { color-scheme: light dark; --line:#d6d9de; --dim:#6b7280; --empty:#e8590c; --info:#adb5bd; --err:#c92a2a; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", sans-serif;
         margin: 0 auto; padding: 24px; max-width: 1100px; line-height: 1.5; }
  h1 { font-size: 20px; margin: 0 0 4px; }
  .sub { color: var(--dim); font-size: 13px; margin-bottom: 20px; }
  fieldset { border: 1px solid var(--line); border-radius: 8px; padding: 14px; margin-bottom: 16px; }
  legend { font-size: 13px; color: var(--dim); padding: 0 6px; }
  input, select, button { font: inherit; padding: 7px 10px; border: 1px solid var(--line); border-radius: 6px; }
  button { cursor: pointer; }
  button[disabled] { opacity: .5; cursor: default; }
  #results { margin-top: 12px; max-height: 260px; overflow-y: auto; }
  #results label { display: block; padding: 7px 4px; border-bottom: 1px solid var(--line); cursor: pointer; }
  #results .meta { color: var(--dim); font-size: 12px; margin-left: 6px; }
  #notice { background: #fff4e6; border: 1px solid #ffd8a8; color: #8a5a1b; padding: 10px 12px;
            border-radius: 8px; font-size: 13px; margin-bottom: 14px; }
  @media (prefers-color-scheme: dark) { #notice { background:#3a2c17; border-color:#6b5220; color:#f0c992; } }
  progress { width: 320px; vertical-align: middle; }
  .hide { display: none; }
  .status { color: var(--dim); font-size: 13px; }
</style>
</head>
<body>

<h1>청약홈 미계약 세대 스캐너</h1>
<div class="sub">단지를 고르면 전 동·전 호의 분양권 정보 등록 여부를 한 번에 확인합니다.</div>

<fieldset>
  <legend>1. 단지 찾기</legend>
  <form id="search-form">
    <input id="q" placeholder="단지명 (예: 상봉 센트럴)" size="28" autofocus>
    <select id="area">
      <option value="">시도 전체</option>
    </select>
    <button type="submit">검색</button>
  </form>
  <div id="results"></div>
  <div id="search-status" class="status"></div>
  <button id="more" class="hide" type="button">더 보기</button>
</fieldset>

<fieldset>
  <legend>2. 스캔</legend>
  <button id="scan-button" disabled>전체 스캔</button>
  <button id="stop-button" class="hide">중단</button>
  <span id="progress" class="status"></span>
</fieldset>

<div id="notice" class="hide">
  이 결과는 청약홈에 분양권 정보가 등록되지 않은 세대입니다.
  미계약·부적격 세대일 가능성이 높으나, 사업주체의 등록 지연일 수도 있으므로 참고용으로만 활용하세요.
</div>

<div id="grids"></div>
<div id="empty-list"></div>

<script>
const AREAS = ["강원","경기","경남","경북","광주","대구","대전","부산","서울","세종",
               "울산","인천","전남","전북","제주","충남","충북"];

const el = (id) => document.getElementById(id);
const state = {
  complex: null, meta: null, units: new Map(), token: null, source: null,
  search: { name: "", area: "", page: 1, loaded: 0, total: 0 },
};

AREAS.forEach((name) => {
  const option = document.createElement("option");
  option.value = option.textContent = name;
  el("area").append(option);
});

el("search-form").addEventListener("submit", (event) => {
  event.preventDefault();
  state.search = {
    name: el("q").value.trim(), area: el("area").value, page: 1, loaded: 0, total: 0,
  };
  el("results").innerHTML = "";
  el("more").classList.add("hide");
  loadPage();
});

el("more").addEventListener("click", () => {
  state.search.page += 1;
  loadPage();
});

async function loadPage() {
  const { name, area, page } = state.search;
  el("search-status").textContent = "검색 중…";
  el("more").disabled = true;
  try {
    const params = new URLSearchParams({ name, area, page: String(page) });
    const response = await fetch("/api/search?" + params);
    const body = await response.json();
    if (!response.ok) throw new Error(body.message || "검색 실패");
    renderResults(body);
  } catch (error) {
    el("search-status").textContent = "검색에 실패했습니다: " + error.message;
  } finally {
    el("more").disabled = false;
  }
}

function renderResults(body) {
  state.search.total = body.total;
  state.search.loaded += body.complexes.length;

  if (!state.search.loaded) {
    el("search-status").textContent = "검색 결과가 없습니다.";
    el("more").classList.add("hide");
    return;
  }
  el("search-status").textContent = `${state.search.loaded}건 표시 (전체 ${body.total}건)`;
  el("more").classList.toggle("hide", state.search.loaded >= body.total);

  body.complexes.forEach((item) => {
    const label = document.createElement("label");
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "complex";
    radio.addEventListener("change", () => {
      state.complex = item;
      el("scan-button").disabled = false;
    });
    label.append(radio, " " + item.name);
    const meta = document.createElement("span");
    meta.className = "meta";
    meta.textContent = `공고 ${item.notice_date} · 당첨발표 ${item.winner_date} · ${item.house_manage_no}`;
    label.append(meta);
    el("results").append(label);
  });
}

el("scan-button").addEventListener("click", () => {
  if (!state.complex) return;
  state.meta = null;
  state.units = new Map();
  state.token = null;
  el("grids").innerHTML = "";
  el("empty-list").innerHTML = "";
  el("notice").classList.add("hide");
  el("scan-button").disabled = true;
  el("stop-button").classList.remove("hide");

  const params = new URLSearchParams({
    hm: state.complex.house_manage_no,
    pb: state.complex.pblanc_no,
  });
  const source = new EventSource("/api/scan?" + params);
  state.source = source;

  source.addEventListener("meta", (event) => {
    state.meta = JSON.parse(event.data);
    el("progress").textContent = `0 / ${state.meta.total}`;
    onMeta(state.meta);
  });

  source.addEventListener("unit", (event) => {
    const unit = JSON.parse(event.data);
    state.units.set(unit.dong + "-" + unit.ho, unit);
    onUnit(unit);
    el("progress").textContent = `${state.units.size} / ${state.meta.total}`;
  });

  source.addEventListener("done", (event) => {
    const summary = JSON.parse(event.data);
    state.token = summary.token;
    el("progress").textContent =
      `완료 · ${summary.total}세대 중 정보없음 ${summary.empty}건` +
      (summary.error ? ` · 실패 ${summary.error}건` : "") +
      ` (${summary.elapsed}초)`;
    finishScan();
    onDone(summary);
  });

  source.addEventListener("error", (event) => {
    if (event.data) {
      const payload = JSON.parse(event.data);
      el("progress").textContent = payload.message;
    } else if (state.units.size === 0) {
      el("progress").textContent = "서버 연결이 끊겼습니다.";
    }
    finishScan();
  });
});

el("stop-button").addEventListener("click", () => {
  el("progress").textContent = `중단됨 · ${state.units.size}세대까지 조회`;
  finishScan();
});

function finishScan() {
  if (state.source) { state.source.close(); state.source = null; }
  el("scan-button").disabled = false;
  el("stop-button").classList.add("hide");
}

// Task 10 에서 채운다
function onMeta(meta) {}
function onUnit(unit) {}
function onDone(summary) {}
</script>
</body>
</html>
```

- [ ] **Step 3: 서버를 띄우고 검색이 도는지 확인한다**

```bash
python3 app.py
```

브라우저에서 단지명에 `상봉`을 넣고 검색한다.
Expected: 단지 목록이 라디오 버튼으로 뜨고, 하나를 고르면 `전체 스캔` 버튼이 활성화된다.

이어서 단지명을 비우고 시도를 `서울`로 두어 검색한다.
Expected: `10건 표시 (전체 168건)`과 함께 `더 보기` 버튼이 뜬다.
누를 때마다 10건씩 아래로 붙고, 전부 불러오면 버튼이 사라진다.

- [ ] **Step 4: 스캔을 눌러 진행률이 오르는지 확인한다**

`상봉 센트럴 아이파크`를 골라 `전체 스캔`을 누른다.
Expected: `0 / 312` 형태로 시작해 숫자가 올라가고, 끝나면 `완료 · 312세대 중 정보없음 N건 (…초)`가 표시된다. 그리드는 아직 비어 있다 (Task 10에서 그린다).

- [ ] **Step 5: 커밋**

```bash
git add app.py static/index.html
git commit -m "feat: 검색과 스캔 진행률 UI 추가"
```

---

### Task 10: `static/index.html` — 격자·상세·정보없음 목록

**Files:**
- Modify: `static/index.html` (`onMeta` / `onUnit` / `onDone` 구현부와 스타일 추가)

**Interfaces:**
- Consumes: Task 9의 `state`, `el()`, `onMeta`/`onUnit`/`onDone` 자리, `meta.dongs[].grid` (Task 5가 실어 보낸 `grid.build_grid` 결과), Task 8의 `GET /api/unit`·`GET /api/export`
- Produces: 없음 (최종 화면)

- [ ] **Step 1: 스타일 추가**

`<style>` 블록 끝에 이어 붙인다:

```css
  .dong { margin: 20px 0; }
  .dong h3 { font-size: 15px; margin: 0 0 8px; }
  table.grid { border-collapse: collapse; font-size: 11px; }
  table.grid th { color: var(--dim); font-weight: 400; padding: 2px 5px; }
  table.grid td { padding: 1px; }
  .cell { width: 26px; height: 22px; border: 1px solid var(--line); border-radius: 3px;
          background: transparent; cursor: pointer; font-size: 10px; color: transparent; }
  .cell.info  { background: var(--info); }
  .cell.empty { background: var(--empty); color: #fff; }
  .cell.error { background: var(--err); color: #fff; }
  .flat { display: flex; flex-wrap: wrap; gap: 3px; }
  .flat .cell { width: 44px; color: inherit; }
  .flat .cell.info { color: #fff; }
  .legend { font-size: 12px; color: var(--dim); margin-top: 8px; }
  .swatch { display: inline-block; width: 11px; height: 11px; border-radius: 2px;
            vertical-align: -1px; margin: 0 3px 0 10px; }
  #detail { position: sticky; bottom: 0; background: Canvas; border-top: 1px solid var(--line);
            padding: 10px 0; font-size: 13px; }
  #detail table { border-collapse: collapse; }
  #detail td { padding: 2px 10px 2px 0; }
  #detail td:first-child { color: var(--dim); }
  table.list { border-collapse: collapse; font-size: 13px; margin-top: 8px; width: 100%; }
  table.list th, table.list td { text-align: left; padding: 5px 8px; border-bottom: 1px solid var(--line); }
  table.list th { color: var(--dim); font-weight: 400; }
```

- [ ] **Step 2: `#empty-list` 아래에 상세 패널을 넣는다**

`<div id="empty-list"></div>` 바로 다음 줄에 추가한다:

```html
<div id="detail"></div>
```

- [ ] **Step 3: `onMeta` / `onUnit` / `onDone` 구현**

Task 9에서 비워둔 세 함수를 아래 코드로 교체한다:

```javascript
function cellId(dong, ho) { return `c-${dong}-${ho}`; }

function makeCell(dong, ho) {
  const button = document.createElement("button");
  button.className = "cell";
  button.id = cellId(dong, ho);
  button.textContent = ho;
  button.title = `${dong}동 ${ho}호`;
  button.addEventListener("click", () => showDetail(dong, ho));
  return button;
}

function onMeta(meta) {
  el("notice").classList.remove("hide");
  const container = el("grids");
  meta.dongs.forEach((dong) => {
    const box = document.createElement("div");
    box.className = "dong";
    const title = document.createElement("h3");
    title.textContent = `${dong.name}동 · ${dong.hos.length}세대`;
    box.append(title);
    box.append(dong.grid ? buildGridTable(dong) : buildFlatList(dong));
    container.append(box);
  });
}

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

function buildFlatList(dong) {
  const box = document.createElement("div");
  box.className = "flat";
  dong.hos.forEach((ho) => box.append(makeCell(dong.name, ho)));
  return box;
}

function onUnit(unit) {
  const cell = document.getElementById(cellId(unit.dong, unit.ho));
  if (cell) cell.classList.add(unit.status);
}

function onDone(summary) {
  renderLegend(summary);
  renderEmptyList();
  renderActions(summary);
}

function renderActions(summary) {
  if (state.token) {
    el("empty-list").insertAdjacentHTML(
      "afterbegin",
      `<p><a href="/api/export?token=${state.token}" download>CSV로 내려받기</a></p>`
    );
  }
  if (summary.error) renderRetry(summary);
}

function renderRetry(summary) {
  const button = document.createElement("button");
  button.textContent = `조회 실패 ${summary.error}건 다시 시도`;
  button.addEventListener("click", async () => {
    button.disabled = true;
    button.textContent = "다시 시도하는 중…";
    const failed = [...state.units.values()].filter((unit) => unit.status === "error");
    for (const unit of failed) {
      const params = new URLSearchParams({
        hm: state.complex.house_manage_no,
        pb: state.complex.pblanc_no,
        dong: unit.dong,
        ho: unit.ho,
        token: state.token || "",
      });
      try {
        const fresh = await (await fetch("/api/unit?" + params)).json();
        state.units.set(fresh.dong + "-" + fresh.ho, fresh);
        const cell = document.getElementById(cellId(fresh.dong, fresh.ho));
        if (cell) {
          cell.classList.remove("error", "info", "empty");
          cell.classList.add(fresh.status);
        }
      } catch (error) {
        // 이 세대는 그대로 두고 다음으로 넘어간다
      }
    }
    const tally = { info: 0, empty: 0, error: 0 };
    state.units.forEach((unit) => { tally[unit.status] = (tally[unit.status] || 0) + 1; });
    const updated = { ...summary, ...tally };
    renderLegend(updated);
    renderEmptyList();
    renderActions(updated);
  });
  el("empty-list").prepend(button);
}

function renderLegend(summary) {
  document.querySelectorAll(".legend").forEach((node) => node.remove());
  const legend = document.createElement("div");
  legend.className = "legend";
  legend.innerHTML =
    `<span class="swatch" style="background:var(--info)"></span>정보있음 ${summary.info}` +
    `<span class="swatch" style="background:var(--empty)"></span>정보없음 ${summary.empty}` +
    (summary.error ? `<span class="swatch" style="background:var(--err)"></span>조회실패 ${summary.error}` : "");
  el("grids").append(legend);
}

// 정보없음 응답에는 값이 하나도 실려 오지 않는다 (라벨만 있고 주택형·공급유형 칸이 비어 있다).
// 그래서 같은 동·같은 라인(호수 끝 두 자리)의 정보있음 세대에서 주택형을 빌려와 참고값으로 보여준다.
function referenceType(dong, ho) {
  if (ho.length < 3) return "";
  const line = ho.slice(-2);
  for (const unit of state.units.values()) {
    if (unit.dong === dong && unit.status === "info" && unit.ho.slice(-2) === line) {
      return unit.fields["주택형"] || "";
    }
  }
  return "";
}

function renderEmptyList() {
  const empties = [...state.units.values()]
    .filter((unit) => unit.status === "empty")
    .sort((a, b) => a.dong.localeCompare(b.dong) || Number(a.ho) - Number(b.ho));

  if (!empties.length) {
    el("empty-list").innerHTML = "<p>정보없음 세대가 없습니다.</p>";
    return;
  }
  const rows = empties
    .map((unit) => {
      const type = referenceType(unit.dong, unit.ho);
      return `<tr><td>${unit.dong}</td><td>${unit.ho}</td><td>${type}</td></tr>`;
    })
    .join("");
  el("empty-list").innerHTML =
    `<h3>정보없음 ${empties.length}세대</h3>` +
    `<table class="list"><thead><tr><th>동</th><th>호</th><th>주택형(참고)</th></tr></thead>` +
    `<tbody>${rows}</tbody></table>`;
}

function showDetail(dong, ho) {
  const unit = state.units.get(dong + "-" + ho);
  if (!unit) return;
  if (unit.status !== "info") {
    const label = unit.status === "empty" ? "정보없음 (미계약·부적격 추정)" : "조회 실패";
    el("detail").innerHTML = `<b>${dong}동 ${ho}호</b> — ${label}`;
    return;
  }
  const rows = Object.entries(unit.fields)
    .map(([key, value]) => `<tr><td>${key}</td><td>${value || "-"}</td></tr>`)
    .join("");
  el("detail").innerHTML = `<b>${dong}동 ${ho}호</b><table>${rows}</table>`;
}
```

- [ ] **Step 4: 브라우저에서 확인한다**

```bash
python3 app.py
```

`상봉 센트럴 아이파크`를 스캔한다.

Expected:
- 스캔 시작과 동시에 동별 격자가 회색 테두리로 먼저 그려진다
- 결과가 도착하는 대로 칸이 채워진다 (회색 = 정보있음, 주황 = 정보없음)
- 완료 후 범례에 건수가 뜨고, 아래에 `정보없음 N세대` 표가 동·호 순으로 나온다
- 표의 `주택형(참고)` 칸에 같은 라인 세대의 주택형이 채워진다 (같은 라인에 정보있음 세대가 없으면 빈칸)
- 주황 칸을 클릭하면 하단에 `정보없음 (미계약·부적격 추정)`이, 회색 칸을 클릭하면 15개 필드 표가 뜬다
- `CSV로 내려받기`를 누르면 파일이 저장되고 엑셀에서 한글이 깨지지 않는다
- 결과 위에 추정 관련 안내 문구가 떠 있다

101동 기준 정보없음 세대는 `305, 502, 603, 1105, 1401, 1404, 1405, 2004, 2302, 2303` 10건이어야 한다 (2026-07-24 실측).

조회 실패가 한 건이라도 났다면 `조회 실패 N건 다시 시도` 버튼이 보인다.
눌러서 실패 칸이 회색이나 주황으로 바뀌고 범례 건수가 갱신되는지, 그 뒤 내려받은 CSV에도 반영되는지 확인한다.

- [ ] **Step 5: 커밋**

```bash
git add static/index.html
git commit -m "feat: 동별 격자와 정보없음 목록 UI 추가"
```

---

### Task 11: 라이브 회귀 테스트와 실행 문서

**Files:**
- Create: `tests/test_live.py`
- Create: `README.md`

**Interfaces:**
- Consumes: `applyhome`, `scanner` 전체
- Produces: 없음 (검증과 문서)

- [ ] **Step 1: 라이브 테스트 작성**

`tests/test_live.py`:

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

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import applyhome
import scanner

LIVE = os.environ.get("APPLYHOME_LIVE") == "1"

SANGBONG = ("2025000439", "2025000439")
EXPECTED_EMPTY_101 = {"305", "502", "603", "1105", "1401", "1404", "1405", "2004", "2302", "2303"}


@unittest.skipUnless(LIVE, "APPLYHOME_LIVE=1 일 때만 실행합니다")
class LiveTest(unittest.TestCase):
    def test_상봉_101동_정보없음_10건이_그대로다(self):
        hm, pb = SANGBONG
        events = []
        scanner.scan_complex(hm, pb, lambda name, payload: events.append((name, payload)))

        units = [payload for name, payload in events if name == "unit"]
        dong_101 = [u for u in units if u["dong"] == "101"]
        self.assertEqual(len(dong_101), 119, "101동 세대 수가 119가 아닙니다")

        empties = {u["ho"] for u in dong_101 if u["status"] == "empty"}
        self.assertEqual(empties, EXPECTED_EMPTY_101)

    def test_장위_1001동_201호는_정보가_있다(self):
        unit = applyhome.fetch_detail("2026000275", "2026000275", "1001", "201")
        self.assertEqual(unit.status, "info")
        self.assertEqual(unit.fields["주택명"], "장위 푸르지오 마크원")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 기본 실행에서 건너뛰는지 확인한다**

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS — `test_live` 2건이 skipped로 표시되고 나머지는 전부 ok

- [ ] **Step 3: 라이브 테스트를 한 번 돌려본다**

Run: `APPLYHOME_LIVE=1 python3 -m unittest tests.test_live -v`
Expected: PASS.

실패하면 청약홈 데이터가 갱신된 것이다 (미계약분이 계약되었을 수 있다).
그 경우 실제 값을 확인해 `EXPECTED_EMPTY_101`을 갱신하고, 갱신 날짜를 docstring에 적는다.

- [ ] **Step 4: `README.md` 작성**

````markdown
# 청약홈 미계약 세대 스캐너

청약홈 「분양권 정보(전매제한 등) 안내」 페이지는 동·호수를 하나씩 골라야만 세대 정보를 볼 수 있다.
이 도구는 한 단지의 전 동·전 호를 자동으로 훑어, 분양권 정보가 등록되지 않은 세대를 한 화면에 모아 보여준다.

## 실행

```bash
python3 app.py
```

브라우저가 `http://127.0.0.1:8765` 로 열린다. 설치할 패키지는 없다 (표준 라이브러리만 쓴다).

## 쓰는 법

1. 단지명을 검색해 대상 단지를 고른다
2. `전체 스캔`을 누른다 — 300세대 기준 15~20초
3. 주황색 칸이 **정보없음** 세대다. 칸을 누르면 상세가 뜬다
4. `CSV로 내려받기`로 결과를 저장한다

## 판정 기준

청약홈은 분양권 정보가 없는 세대를 조회하면 다음 경고창을 띄운다.

> 해당 [동:xxx, 호:xxx]에 대한 분양권 세부 정보가 없습니다.

이 도구는 청약홈 스크립트와 **같은 조건**(상세 응답의 `id="houseManageNo"` 가 비었는지)으로 판정한다.

**주의** — `정보없음`은 "청약홈에 분양권 정보가 등록되지 않았다"는 사실만 뜻한다.
미계약·부적격 세대일 가능성이 높지만, 사업주체가 계약 건을 아직 등록하지 않았을 수도 있다. 참고용으로만 쓸 것.

## 테스트

```bash
python3 -m unittest discover -s tests -v          # 저장된 응답으로만 (네트워크 불필요)
APPLYHOME_LIVE=1 python3 -m unittest tests.test_live -v   # 청약홈에 실제로 붙는 회귀 테스트
```

## 청약홈 서버 배려

공공 사이트이므로 동시 요청 4개, 요청 간 0.1초 간격, 실패 시 3회 재시도로 제한한다.
이 값은 `scanner.scan_complex`의 `max_workers`, `delay` 인자와 `applyhome.RETRIES` 에 있다.
````

- [ ] **Step 5: 전체 테스트 최종 확인**

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS — 라이브 2건 skipped, 나머지 전부 ok

- [ ] **Step 6: 커밋**

```bash
git add tests/test_live.py README.md
git commit -m "test: 실측 기반 라이브 회귀 테스트와 실행 문서 추가"
```

---

## 완료 기준

- [ ] `python3 -m unittest discover -s tests -v` 가 전부 통과한다 (라이브 2건은 skip)
- [ ] `python3 app.py` 로 서버가 뜨고 브라우저가 열린다
- [ ] 단지를 검색해 고를 수 있고, 결과가 10건을 넘으면 `더 보기`로 이어 볼 수 있다
- [ ] 스캔하면 격자가 실시간으로 채워진다
- [ ] 정보없음 세대가 주황색으로 구분되고, 아래 표에 동·호·주택형(참고)이 나열된다
- [ ] 조회 실패가 있으면 재시도 버튼으로 복구되고, 그 결과가 CSV에도 반영된다
- [ ] CSV를 내려받아 엑셀에서 열면 한글이 깨지지 않는다
- [ ] 결과 화면에 추정 관련 안내 문구가 항상 보인다
