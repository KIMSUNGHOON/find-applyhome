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
