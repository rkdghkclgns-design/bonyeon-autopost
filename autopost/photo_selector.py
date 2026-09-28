"""포스팅할 카테고리와 사진 선택.

사진은 옮기지 않고 드라이브에 '사용 횟수'만 기록한다. 한 번도 안 쓴 사진이 먼저(올린 순서대로 —
같은 현장 사진끼리 함께), 다 쓴 뒤에는 덜 쓴 사진부터 무작위로 섞어 매번 다른 조합이 되게 한다.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Sequence

from .constants import CATEGORIES, STAGES
from .drive_helper import DriveFile, DriveHelper
from .setup_engine import DriveLayout


class UnknownCategoryError(ValueError):
    pass


@dataclass(frozen=True)
class PhotoSelection:
    category: str
    files_by_stage: Mapping[str, tuple[DriveFile, ...]]

    @property
    def total(self) -> int:
        return sum(len(files) for files in self.files_by_stage.values())

    def all_files(self) -> tuple[DriveFile, ...]:
        return tuple(f for stage in STAGES for f in self.files_by_stage.get(stage, ()))

    @property
    def reused(self) -> bool:
        """이전 포스팅에 쓴 사진이 섞였는지 — 섞였으면 새 현장 글처럼 쓰지 않는다."""
        return any(f.post_count > 0 for f in self.all_files())

    @property
    def fresh_count(self) -> int:
        return sum(1 for f in self.all_files() if f.post_count == 0)


def usage_order(files: Sequence[DriveFile], rng: random.Random) -> list[DriveFile]:
    """안 쓴 사진(올린 순서) → 덜 쓴 사진(같은 횟수끼리는 무작위) 순."""
    return sorted(
        files,
        key=lambda f: (f.post_count, f.created_time if f.post_count == 0 else "", rng.random()),
    )


def resolve_category(requested: str) -> str | None:
    """'로프', '02_로프청소', '로프청소' 등 입력을 카테고리명으로 변환. 빈 값이면 None."""
    text = requested.strip().replace(" ", "")
    if not text:
        return None
    for category in CATEGORIES:
        if text in (category.name, category.folder) or text in category.name:
            return category.name
    names = ", ".join(c.name for c in CATEGORIES)
    raise UnknownCategoryError(f"알 수 없는 카테고리 '{requested}' (사용 가능: {names})")


def _category_of(token: str) -> str | None:
    try:
        return resolve_category(token)
    except UnknownCategoryError:
        return None


def split_request(text: str) -> tuple[str, str]:
    """'정기청소 고잔동' / '고잔동 로프' / '안산 중앙동' → (카테고리 입력, 현장 위치).

    카테고리로 인식되는 첫 단어를 카테고리로, 나머지를 현장 위치로 본다.
    """
    tokens = text.split()
    for index, token in enumerate(tokens):
        if _category_of(token):
            return token, " ".join(tokens[:index] + tokens[index + 1:])
    return "", " ".join(tokens)


@dataclass(frozen=True)
class _Pool:
    """카테고리의 전체 사진 (단계별, 사용 순서로 정렬)."""
    category: str
    files_by_stage: Mapping[str, tuple[DriveFile, ...]]

    def _all(self) -> tuple[DriveFile, ...]:
        return tuple(f for files in self.files_by_stage.values() for f in files)

    @property
    def fresh(self) -> int:
        return sum(1 for f in self._all() if f.post_count == 0)

    @property
    def last_posted(self) -> str:
        return max((f.last_posted for f in self._all()), default="")

    def pick(self, per_stage: int) -> PhotoSelection:
        return PhotoSelection(self.category, MappingProxyType(
            {stage: files[:per_stage] for stage, files in self.files_by_stage.items()}
        ))


def _pool(drive: DriveHelper, layout: DriveLayout, category: str, rng: random.Random) -> _Pool:
    folders = layout.stage_folders[category]
    return _Pool(category, MappingProxyType({
        stage: tuple(usage_order(drive.list_images(folders[stage]), rng)) for stage in STAGES
    }))


def select_photos(
    drive: DriveHelper,
    layout: DriveLayout,
    requested: str,
    per_stage: int,
    min_photos: int,
    rng: random.Random | None = None,
) -> PhotoSelection | None:
    """요청 카테고리(없으면 새 사진이 가장 많은 카테고리 → 없으면 가장 오래전에 올린 카테고리)에서
    단계별로 사용 순서가 앞선 사진을 고른다."""
    rng = rng or random.Random()
    wanted = resolve_category(requested)
    candidates = [wanted] if wanted else [c.name for c in CATEGORIES]
    picks = [(pool, pool.pick(per_stage)) for pool in (_pool(drive, layout, n, rng) for n in candidates)]
    eligible = [(pool, pick) for pool, pick in picks if pick.total >= min_photos]
    if not eligible:
        return None
    # 새 사진이 많은 카테고리 우선, 동률(모두 0장 포함)이면 가장 오래전에 포스팅한 카테고리 → 카테고리가 돌아가며 올라감
    _, best = min(eligible, key=lambda item: (-item[0].fresh, item[0].last_posted))
    return best
