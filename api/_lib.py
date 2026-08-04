"""엔드포인트 로직. Vercel 함수와 로컬 서버가 함께 쓴다.

각 함수는 parse_qs 결과를 받아 (HTTP 상태, JSON 페이로드) 를 돌려준다.
HTTP 를 직접 다루지 않으므로 서버를 띄우지 않고 테스트할 수 있다.

`_` 로 시작하는 파일이라 Vercel 이 함수로 변환하지 않는다.
"""

from __future__ import annotations

import json
import pathlib
import sys

# applyhome.py / grid.py 는 저장소 루트에 있다. 로컬과 Vercel 양쪽에서 import 되어야 한다.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import applyhome
import _cache
import grid

CACHE = _cache.CacheStore.from_env()


def _cache_call(method: str, *args):
    if CACHE is None:
        return None
    try:
        return getattr(CACHE, method)(*args)
    except Exception:
        return None


def respond(request, status: int, payload: dict) -> None:
    """BaseHTTPRequestHandler 에 JSON 을 써 보낸다. Vercel 과 로컬이 함께 쓴다."""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request.send_response(status)
    request.send_header("Content-Type", "application/json; charset=utf-8")
    request.send_header("Content-Length", str(len(body)))
    request.end_headers()
    request.wfile.write(body)


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
    payload = {"dongs": [{"sn": d.sn, "name": d.name} for d in found]}
    _cache_call("write_dongs", hm, pb, payload["dongs"])
    return 200, payload


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
    payload = {"hos": numbers, "grid": grid.build_grid(numbers)}
    _cache_call("write_hos", hm, pb, sn, payload["hos"], payload["grid"])
    return 200, payload


def unit(query: dict) -> tuple[int, dict]:
    """세대 1건. 개별 실패가 스캔을 멈추면 안 되므로 실패해도 200 을 돌려준다."""
    hm, pb = one(query, "hm"), one(query, "pb")
    dong, ho = one(query, "dong"), one(query, "ho")
    if not (hm and pb and dong and ho):
        return 400, {"message": "hm, pb, dong, ho 값이 모두 필요합니다."}

    lock = _cache_call("claim_unit", hm, pb, dong, ho)
    if lock is not None and lock.state == "busy":
        cached = _cache_call("read_unit", hm, pb, dong, ho)
        if cached:
            return 200, {**cached, "refreshing": True, "source": "cache"}
        return 202, {
            "dong": dong,
            "ho": ho,
            "status": "refreshing",
            "fields": {},
            "refreshing": True,
        }

    token = lock.token if lock is not None and lock.state == "acquired" else None
    try:
        try:
            found = applyhome.fetch_detail(hm, pb, dong, ho)
        except applyhome.ApplyhomeError as error:
            saved = _cache_call(
                "record_unit_error", hm, pb, dong, ho, str(error), token,
            )
            if saved:
                return 200, {**saved, "refresh_error": True}
            return 200, {
                "dong": dong,
                "ho": ho,
                "status": "error",
                "fields": {},
                "message": str(error),
            }
        payload = {
            "dong": found.dong,
            "ho": found.ho,
            "status": found.status,
            "fields": found.fields,
        }
        _cache_call("write_unit", hm, pb, payload, token)
        return 200, payload
    finally:
        if token:
            _cache_call("release_unit", hm, pb, dong, ho, token)


def pblanc(query: dict) -> tuple[int, dict]:
    """공고 타입별 공급세대수. 실패 여부를 분리하면서 200 fail-open을 유지한다."""
    hm, pb = one(query, "hm"), one(query, "pb")
    if not (hm and pb):
        return 400, {"message": "hm, pb 값이 필요합니다."}
    try:
        types = applyhome.fetch_pblanc_supply(hm, pb)
    except Exception:
        return 200, {"supply": None, "refresh_failed": True}
    supply = [
        {
            "type": item.house_type,
            "short": grid.short_type(item.house_type),
            "net_area": grid.net_area(item.house_type),
            "area": item.area,
            "general": item.general,
            "special": item.special,
            "total": item.total,
        }
        for item in types
    ] or None
    payload = {"supply": supply, "refresh_failed": False}
    _cache_call("write_supply", hm, pb, supply)
    return 200, payload


def cache_snapshot(query: dict) -> tuple[int, dict]:
    hm, pb = one(query, "hm"), one(query, "pb")
    if not (hm and pb):
        return 400, {"message": "hm, pb 값이 필요합니다."}
    request_full = one(query, "refresh") == "full"
    if CACHE is None:
        return 200, {
            "cache": "disabled",
            "complete": False,
            "checked_at": None,
            "meta": None,
            "units": [],
            "refresh": {
                "topology": True,
                "supply": True,
                "all_units": True,
                "units": [],
            },
            "full_refresh": {"allowed": True, "retry_after": 0},
        }
    try:
        body = CACHE.read_snapshot(hm, pb, request_full=request_full)
        cache_state = body["cache"]
        refresh_all = body["refresh"]["all_units"]
    except Exception:
        return 200, {
            "cache": "disabled",
            "complete": False,
            "checked_at": None,
            "meta": None,
            "units": [],
            "refresh": {
                "topology": True,
                "supply": True,
                "all_units": True,
                "units": [],
            },
            "full_refresh": {"allowed": True, "retry_after": 0},
        }
    if request_full or (cache_state == "stale" and refresh_all):
        body["full_refresh"] = (
            _cache_call("claim_full_refresh", hm, pb)
            or {"allowed": True, "retry_after": 0}
        )
    return 200, body


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


ROUTES = {
    "/api/search": search,
    "/api/dongs": dongs,
    "/api/hos": hos,
    "/api/unit": unit,
    "/api/pblanc": pblanc,
    "/api/cache": cache_snapshot,
    "/api/visits": visits,
}
