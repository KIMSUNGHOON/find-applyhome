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

    on_event("meta", {"total": len(jobs), "dongs": meta_dongs, "supply": _supply(client, hm, pb)})

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
