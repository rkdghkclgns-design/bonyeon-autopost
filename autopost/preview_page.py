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
</style></head>
<body><main>
<div class="note">{note}</div>
<h1>{title}</h1>
{body}
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
    return PAGE.format(title=html.escape(content.title), note=html.escape(note), body=body)


def write_preview(out_path: Path, *args, **kwargs) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_preview(*args, **kwargs), encoding="utf-8")
    return out_path


NAVER_PAGE = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>[네이버] {title}</title>
<style>
  body {{ margin:0; background:#f5f6f7; font-family:'Nanum Gothic','나눔고딕','Malgun Gothic',sans-serif; color:#333; }}
  .top {{ background:#03c75a; color:#fff; padding:12px 16px; font-weight:bold; }}
  main {{ max-width:693px; margin:0 auto; background:#fff; padding:28px 20px 48px; }}
  .note {{ background:#fff8e1; border:1px solid #f0d58a; border-radius:8px; padding:10px 14px; font-size:.9em; margin-bottom:20px; }}
  h1 {{ font-size:1.6em; line-height:1.4; margin:4px 0 8px; font-weight:normal; }}
  .meta {{ color:#999; font-size:.85em; border-bottom:1px solid #eee; padding-bottom:16px; margin-bottom:28px; }}
  .body {{ text-align:center; }}
  p {{ margin:0; font-size:16px; line-height:1.8; min-height:1.8em; }}
  p.rule {{ color:#146c94; letter-spacing:-1px; }}
  p.heading {{ font-weight:bold; font-size:17px; }}
  img {{ display:block; max-width:100%; margin:12px auto; }}
  .tags {{ margin-top:36px; border-top:1px solid #eee; padding-top:16px; }}
  .tags span {{ display:inline-block; color:#03c75a; margin:0 10px 8px 0; font-size:.95em; }}
</style></head>
<body><div class="top">네이버 블로그 미리보기</div><main>
<div class="note">{note}</div>
<h1>{title}</h1>
<div class="meta">{blog} · 에디터에 입력되는 순서·줄바꿈 그대로</div>
<div class="body">
{body}
</div>
<div class="tags">{tags}</div>
</main></body></html>
"""


def render_naver_preview(
    content: PostContent,
    photos_by_stage: Mapping[str, Sequence[Path]],
    header: Path | None = None,
    footer: Path | None = None,
    comparison: Path | None = None,
    reviews: Sequence[Path] = (),
    note: str = "미리보기 — 아직 어디에도 게시되지 않았습니다.",
    blog: str = "네이버 블로그",
) -> str:
    """네이버 스마트에디터에 들어가는 블록(가운데 정렬, 글 한 줄 = 한 문단, 빈 줄 = 빈 문단) 순서 그대로 보여준다."""
    from .naver_publisher import HEADING_RULE, build_blocks  # 네이버 모듈은 필요할 때만

    parts: list[str] = []
    for block in build_blocks(content, photos_by_stage, header, footer, comparison, reviews):
        if block.kind == "image" and block.image is not None:
            if block.image.is_file():
                parts.append(f'<img src="{data_uri(block.image)}" alt="">')
            continue
        if block.kind == "heading":  # 발행 시 입력과 같게: 줄 / 굵은 소제목 / 줄 / 빈 줄
            rule = f'<p class="rule">{HEADING_RULE}</p>'
            parts += [rule, f'<p class="heading">{html.escape(block.text.strip())}</p>', rule, "<p>&nbsp;</p>"]
            continue
        for line in block.text.split("\n"):  # 발행 시 줄마다 Enter — 빈 줄은 빈 문단
            parts.append(f"<p>{html.escape(line.strip())}</p>" if line.strip() else "<p>&nbsp;</p>")
        parts.append("<p>&nbsp;</p>")
    tags = "".join(f"<span>{html.escape(tag)}</span>" for tag in content.hashtags)
    return NAVER_PAGE.format(title=html.escape(content.title), note=html.escape(note), blog=html.escape(blog),
                             body="\n".join(parts), tags=tags)


def write_naver_preview(out_path: Path, *args, **kwargs) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_naver_preview(*args, **kwargs), encoding="utf-8")
    return out_path
