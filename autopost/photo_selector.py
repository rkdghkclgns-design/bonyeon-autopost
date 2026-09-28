"""포스팅할 카테고리와 사진 선택."""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

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


def collect_category(
    drive: DriveHelper, layout: DriveLayout, category: str, per_stage: int
) -> PhotoSelection:
    folders = layout.stage_folders[category]
    files_by_stage = {
        stage: tuple(drive.list_images(folders[stage])[:per_stage]) for stage in STAGES
    }
    return PhotoSelection(category, MappingProxyType(files_by_stage))


def select_photos(
    drive: DriveHelper,
    layout: DriveLayout,
    requested: str,
    per_stage: int,
    min_photos: int,
) -> PhotoSelection | None:
    """요청 카테고리(없으면 사진이 가장 많은 카테고리)에서 단계별 오래된 사진부터 선택."""
    wanted = resolve_category(requested)
    candidates = [wanted] if wanted else [c.name for c in CATEGORIES]
    selections = [collect_category(drive, layout, name, per_stage) for name in candidates]
    best = max(selections, key=lambda s: s.total)  # 동점이면 먼저 나온 카테고리
    return best if best.total >= min_photos else None
