"""호수 문자열을 층·라인 격자로 배치한다.

호수 마지막 두 자리가 라인, 그 앞이 층이다. "1105" → 11층 05라인.
이 규칙에 맞지 않는 호수가 하나라도 섞이면 격자를 포기하고 None을 돌려준다.
호출한 쪽은 None을 받으면 단순 나열로 표시한다.
"""

from __future__ import annotations

import re


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
