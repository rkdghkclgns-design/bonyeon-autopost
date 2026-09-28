"""서비스 지역 → 동 단위 키워드 순환.

SERVICE_AREA 예: "서울,경기,인천,안산"
- 각 항목은 시·도(서울/경기/인천) 또는 시·군·구(안산, 강남구 …) 이름과 매칭된다.
- 포스팅마다 날짜 순서대로 [항목 → 시군구 → 동] 을 돌아가며 하나씩 고른다.
  (항목끼리 번갈아, 한 항목 안에서는 시군구를 번갈아 → 같은 구가 연달아 나오지 않음)
- 실제 현장 위치를 모를 때 동 이름은 '서비스 가능 지역' 키워드로만 쓴다 (현장이 그 동이라고 쓰지 않음).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from itertools import zip_longest
from pathlib import Path
from typing import Sequence

DATA_FILE = Path(__file__).parent / "data" / "regions.json"
SIDO_SHORT = {"서울특별시": "서울", "경기도": "경기", "인천광역시": "인천"}
SIDO_ALIASES = {"서울": "서울특별시", "경기": "경기도", "인천": "인천광역시"}
NUMBERED_DONG = re.compile(r"제?[\d·]+가?동$")


@dataclass(frozen=True)
class AreaPick:
    city: str  # 서울 / 인천 / 안산 / 화성 …
    district: str = ""  # 강남구 / 단원구 / 강화군 … (없으면 "")
    dong: str = ""  # 고잔동 / 봉담읍 … (검색용으로 정리된 이름)
    is_site: bool = False  # True = 실제 작업 현장 위치 (False = 서비스 지역 키워드)

    @property
    def region(self) -> str:
        return " ".join(p for p in (self.city, self.district) if p)

    @property
    def label(self) -> str:
        return " ".join(p for p in (self.region, self.dong) if p)

    def hashtags(self, category: str) -> tuple[str, ...]:
        tags: list[str] = []
        if self.dong:
            tags += [f"{self.dong}{category}", f"{self.dong}청소"]
        if self.district:
            tags.append(f"{self.district}청소업체")
        if self.city:
            tags += [f"{self.city}{category}", f"{self.city}청소업체"]
        return tuple(dict.fromkeys(tags))


def search_name(dong: str) -> str:
    """행정동 → 사람들이 검색하는 이름 (선부1동→선부동, 상계3·4동→상계동, 화수1·화평동→화수동, 봉담읍 그대로)."""
    if dong.endswith("동") and re.search(r"\d", dong):
        match = re.match(r"^([가-힣]+?)제?\d", dong)
        if match:
            return f"{match.group(1)}동"
    return NUMBERED_DONG.sub("동", dong)


def split_sgg(sgg: str) -> tuple[str, str]:
    """'안산시단원구'/'안산시 단원구' → ('안산', '단원구'), '강남구' → ('', '강남구'), '화성시' → ('화성', '')."""
    match = re.match(r"^(\S+?)[시군]\s?(\S+[구군])$", sgg)
    if match:
        return match.group(1), match.group(2)
    if re.search(r"[시군]$", sgg) and not sgg.endswith("구"):
        return sgg[:-1], ""
    return "", sgg


@lru_cache(maxsize=1)
def _entries() -> tuple[tuple[str, str, str], ...]:
    """(시도, 시군구, 동) 전체 목록."""
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))["regions"]
    return tuple((sido, sgg, dong) for sido, sggs in data.items() for sgg, dongs in sggs.items() for dong in dongs)


def _to_pick(sido: str, sgg: str, dong: str) -> AreaPick:
    if sido in ("서울특별시", "인천광역시"):  # 광역시 안의 구·군은 '인천 강화군' 처럼 시 이름을 앞에
        return AreaPick(city=SIDO_SHORT[sido], district=sgg.replace(" ", ""), dong=search_name(dong))
    city, district = split_sgg(sgg)
    return AreaPick(city=city or SIDO_SHORT.get(sido, sido), district=district, dong=search_name(dong))


def _interleave_by_district(picks: Sequence[AreaPick]) -> tuple[AreaPick, ...]:
    """같은 시군구가 연달아 나오지 않도록 시군구별로 번갈아 배치 (동 이름 중복 제거)."""
    groups: dict[str, list[AreaPick]] = {}
    for pick in picks:
        bucket = groups.setdefault(pick.region, [])
        if pick not in bucket:
            bucket.append(pick)
    return tuple(p for row in zip_longest(*groups.values()) for p in row if p is not None)


@lru_cache(maxsize=32)
def area_group(name: str) -> tuple[AreaPick, ...]:
    """'서울' → 서울 전체 동, '안산' → 안산 상록구·단원구 동, 매칭 실패 시 지역명 그대로 1개."""
    key = name.strip()
    sido = SIDO_ALIASES.get(key, key if key in SIDO_SHORT else None)
    if sido:
        matched = [e for e in _entries() if e[0] == sido]
    else:
        bare = re.sub(r"[시군구]$", "", key)
        matched = [e for e in _entries() if split_sgg(e[1])[0] == bare or e[1] in (key, bare + "구")]
    if not matched:
        return (AreaPick(city=key),)
    return _interleave_by_district([_to_pick(*e) for e in matched])


def pick_area(service_areas: Sequence[str], index: int) -> AreaPick | None:
    """index(예: 날짜 서수)에 따라 [항목 → 시군구 → 동] 을 순환해 하나 선택."""
    groups = [area_group(name) for name in service_areas if name.strip()]
    if not groups:
        return None
    group = groups[index % len(groups)]
    return group[(index // len(groups)) % len(group)]


def site_area(location: str) -> AreaPick | None:
    """사용자가 알려준 실제 현장 위치 → AreaPick (알려진 동이면 시군구까지 보강)."""
    text = location.strip()
    if not text:
        return None
    tokens = text.split()
    last = search_name(tokens[-1])
    hints = [re.sub(r"[시군구]$", "", t) for t in tokens[:-1]]
    candidates = {
        _to_pick(sido, sgg, dong)
        for sido, sgg, dong in _entries()
        if search_name(dong) == last
    }
    if hints:  # '안산 중앙동' 처럼 도시가 함께 오면 그 도시로 좁힘
        candidates = {c for c in candidates if any(h and h in c.region for h in hints)}
    if len(candidates) == 1:  # 동명이 여러 도시에 있으면 추측하지 않는다
        known = candidates.pop()
        return AreaPick(known.city, known.district, known.dong, is_site=True)
    if len(tokens) == 1 and last.endswith(("동", "읍", "면")):
        return AreaPick(city="", dong=last, is_site=True)
    return AreaPick(city=text, is_site=True)
