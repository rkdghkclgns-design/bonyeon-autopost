"""Zero-Touch 셀프 세팅 엔진.

구글 드라이브의 폴더 구조와 기본 템플릿 파일을 검사하고, 없으면 자동 생성한다.
여러 번 실행해도 기존 폴더/파일은 건드리지 않는다(멱등).
"""
from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping

from . import templates
from .constants import (
    BGM_FILE,
    BGM_FOLDER,
    CATEGORIES,
    FOOTER_FILE,
    FOOTER_FOLDER,
    GUIDE_FILE,
    GUIDE_TEXT,
    HEADER_FILE,
    HEADER_FOLDER,
    PUBLIC_ASSET_FOLDER,
    REVIEW_FOLDER,
    STAGES,
)
from .drive_helper import DriveHelper

log = logging.getLogger(__name__)

DRIVE_ROOT_ALIAS = "root"


@dataclass(frozen=True)
class DriveLayout:
    root_id: str
    header_folder_id: str
    footer_folder_id: str
    bgm_folder_id: str
    public_folder_id: str
    # 카테고리명 -> (단계명 -> 폴더 ID)
    stage_folders: Mapping[str, Mapping[str, str]]
    review_folder_id: str = ""


@dataclass(frozen=True)
class SetupReport:
    layout: DriveLayout
    created_folders: tuple[str, ...]
    created_files: tuple[str, ...]

    @property
    def changed(self) -> bool:
        return bool(self.created_folders or self.created_files)


def _ensure(drive: DriveHelper, parent_id: str, name: str, path: str, created: list[str]) -> str:
    folder, is_new = drive.ensure_folder(parent_id, name)
    if is_new:
        created.append(path)
    return folder.id


def _ensure_template(
    drive: DriveHelper,
    folder_id: str,
    file_name: str,
    display_path: str,
    make: Callable[[Path], Path],
    workdir: Path,
    created: list[str],
) -> None:
    if drive.find_child(folder_id, file_name) is not None:
        return
    local = make(workdir / file_name)
    drive.upload(folder_id, local, name=file_name)
    created.append(display_path)
    log.info("기본 템플릿 생성: %s", display_path)


def ensure_layout(
    drive: DriveHelper,
    root_name: str,
    company_name: str,
    company_phone: str,
    create_templates: bool = True,
) -> SetupReport:
    created_folders: list[str] = []
    created_files: list[str] = []

    root_id = _ensure(drive, DRIVE_ROOT_ALIAS, root_name, root_name, created_folders)

    def sub(name: str) -> str:
        return _ensure(drive, root_id, name, f"{root_name}/{name}", created_folders)

    header_id = sub(HEADER_FOLDER)
    footer_id = sub(FOOTER_FOLDER)
    bgm_id = sub(BGM_FOLDER)

    stage_folders: dict[str, Mapping[str, str]] = {}
    for category in CATEGORIES:
        category_id = sub(category.folder)
        stage_folders[category.name] = MappingProxyType({
            stage: _ensure(
                drive, category_id, stage, f"{root_name}/{category.folder}/{stage}", created_folders
            )
            for stage in STAGES
        })

    review_id = sub(REVIEW_FOLDER)
    public_id = sub(PUBLIC_ASSET_FOLDER)

    if create_templates:
        with tempfile.TemporaryDirectory(prefix="autopost_setup_") as tmp:
            workdir = Path(tmp)
            _ensure_template(
                drive, header_id, HEADER_FILE, f"{HEADER_FOLDER}/{HEADER_FILE}",
                lambda p: templates.generate_header(p, company_name), workdir, created_files,
            )
            _ensure_template(
                drive, footer_id, FOOTER_FILE, f"{FOOTER_FOLDER}/{FOOTER_FILE}",
                lambda p: templates.generate_footer(p, company_name, company_phone), workdir, created_files,
            )
            _ensure_template(
                drive, bgm_id, BGM_FILE, f"{BGM_FOLDER}/{BGM_FILE}",
                templates.default_bgm, workdir, created_files,
            )
            _ensure_template(
                drive, root_id, GUIDE_FILE, GUIDE_FILE,
                lambda p: _write_text(p, GUIDE_TEXT), workdir, created_files,
            )

    layout = DriveLayout(
        root_id=root_id,
        header_folder_id=header_id,
        footer_folder_id=footer_id,
        bgm_folder_id=bgm_id,
        public_folder_id=public_id,
        stage_folders=MappingProxyType(stage_folders),
        review_folder_id=review_id,
    )
    return SetupReport(layout, tuple(created_folders), tuple(created_files))


def _write_text(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path
