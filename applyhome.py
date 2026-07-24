"""청약홈 「분양권 정보(전매제한 등)」 페이지의 내부 API 클라이언트.

네트워크 호출과 응답 파싱만 담당한다. 스캔 전략과 서버 로직은 여기 두지 않는다.
"""

from __future__ import annotations

import json
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


@dataclass(frozen=True)
class Dong:
    sn: int      # DONG_SN — selectHoList.do 에 넘긴다
    name: str    # DONG_NM — selectResalePblancDetail.do 에 넘긴다


@dataclass(frozen=True)
class Ho:
    sn: int
    no: str


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
