"""구글 블로그에 올라갈 모습 그대로의 미리보기 페이지.

사진을 페이지 안에 직접 넣어(data URI) 파일 하나만 열면 보이게 한다 — 슬랙 원고 채널에 올려 검토용으로 쓴다.
"""
from __future__ import annotations

import base64
import html
import io
from pathlib import Path
from typing import Mapping, Sequence

from PIL import Image, ImageOps

from .ai_helper import PostContent
from .blog_publisher import build_blog_html
from .constants import STAGES

PREVIEW_MAX_PX = 900  # 미리보기용으로 줄여 파일 크기를 작게

PAGE = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  body {{ margin:0; background:#f4f5f7; font-family:'Malgun Gothic','Apple SD Gothic Neo',sans-serif; color:#222; }}
  main {{ max-width:720px; margin:0 auto; background:#fff; padding:24px 16px 48px; }}
  h1 {{ font-size:1.45em; line-height:1.4; text-align:center; margin:8px 0 24px; }}
  .note {{ background:#fff8e1; border:1px solid #f0d58a; border-radius:8px; padding:10px 14px; font-size:.9em; margin-bottom:20px; }}
  .tiktok {{ margin-top:32px; background:#111; color:#fff; border-radius:10px; padding:16px; white-space:pre-wrap; line-height:1.7; }}
</style></head>
<body><main>
<div class="note">{note}</div>
<h1>{title}</h1>
{body}
<div class="tiktok"><b>틱톡 캡션</b>
{tiktok}</div>
</main></body></html>
"""


def data_uri(path: Path, max_px: int = PREVIEW_MAX_PX) -> str:
    with Image.open(path) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
    image.thumbnail((max_px, max_px))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def render_preview(
    content: PostContent,
    photos_by_stage: Mapping[str, Sequence[Path]],
    header: Path | None = None,
    footer: Path | None = None,
    comparison: Path | None = None,
    reviews: Sequence[Path] = (),
    note: str = "미리보기 — 아직 어디에도 게시되지 않았습니다.",
) -> str:
    def uri(path: Path | None) -> str | None:
        return data_uri(path) if path is not None and path.is_file() else None

    urls = {stage: tuple(data_uri(p) for p in photos_by_stage.get(stage, ())) for stage in STAGES}
    body = build_blog_html(
        content, urls, uri(header), uri(footer), uri(comparison), tuple(data_uri(p) for p in reviews)
    )
    return PAGE.format(
        title=html.escape(content.title), note=html.escape(note), body=body,
        tiktok=html.escape(content.tiktok_caption),
    )


def write_preview(out_path: Path, *args, **kwargs) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_preview(*args, **kwargs), encoding="utf-8")
    return out_path
