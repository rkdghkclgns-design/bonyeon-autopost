"""네이버 블로그 발행 (Playwright + 저장된 로그인 세션).

네이버는 블로그 글쓰기 공개 API가 없어 스마트에디터 ONE 화면을 브라우저로 조작한다.
- 로그인은 scripts/export_naver_cookies.py 로 사람이 직접 1회 수행한 세션을 재사용한다.
- 네이버 UI가 바뀌면 NaverSelectors 값만 수정하면 된다.
- 실패 시 스크린샷을 OUTPUT_DIR 에 남기고, 파이프라인이 슬랙으로 수동 발행용 초안을 보낸다.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from .ai_helper import PostContent
from .blog_publisher import tips_heading
from .constants import REVIEW_CAPTION, REVIEW_HEADING, STAGE_LABELS, STAGES
from .results import PublishResult

log = logging.getLogger(__name__)

PLATFORM = "네이버 블로그"
WRITE_URL = "https://blog.naver.com/{blog_id}/postwrite"
POST_ID_RE = re.compile(r"(?:logNo=|/)(\d{9,})")
MAX_TAGS = 30


class NaverError(RuntimeError):
    pass


class NaverSessionExpired(NaverError):
    pass


@dataclass(frozen=True)
class NaverSelectors:
    main_frame: str = "iframe#mainFrame"
    popup_cancel: str = "button.se-popup-button-cancel"
    help_close: str = "button.se-help-panel-close-button"
    title: str = ".se-documentTitle .se-text-paragraph"
    body_paragraph: str = ".se-component.se-text .se-text-paragraph"
    image_button: str = "button.se-image-toolbar-button"
    image_component: str = ".se-component.se-image"
    publish_button: str = "button[class*='publish_btn']"
    tag_input: str = "input[class*='tag_input']"
    confirm_publish: str = "button[class*='confirm_btn']"
    save_button: str = "button[class*='save_btn']"


@dataclass(frozen=True)
class NaverBlock:
    kind: str  # "text" | "image"
    text: str = ""
    image: Path | None = None


COMPARISON_CAPTION = "작업 전(좌) · 작업 후(우)"


def build_blocks(
    content: PostContent,
    images_by_stage: Mapping[str, Sequence[Path]],
    header: Path | None = None,
    footer: Path | None = None,
    comparison: Path | None = None,
    reviews: Sequence[Path] = (),
) -> tuple[NaverBlock, ...]:
    """소제목 → 도입 → (사진 → 사진 설명) 반복 → 전후 비교 → 고객후기 → 관리 TIP → 맺음말 순서."""
    blocks: list[NaverBlock] = []
    if header is not None:
        blocks.append(NaverBlock("image", image=header))
    blocks.append(NaverBlock("text", text=content.intro))
    for stage in STAGES:
        images = images_by_stage.get(stage, ())
        section = content.section_for(stage)
        if not images and section is None:
            continue
        heading = section.heading if section else STAGE_LABELS[stage]
        blocks.append(NaverBlock("text", text=f"“ {heading} ”"))
        if section:
            blocks.append(NaverBlock("text", text=section.body))
        for index, path in enumerate(images):
            blocks.append(NaverBlock("image", image=path))
            caption = section.caption_for(index) if section else ""
            if caption:
                blocks.append(NaverBlock("text", text=caption))
    if comparison is not None:
        blocks.append(NaverBlock("image", image=comparison))
        blocks.append(NaverBlock("text", text=COMPARISON_CAPTION))
    if reviews:
        blocks.append(NaverBlock("text", text=f"“ {REVIEW_HEADING} ”"))
        blocks.extend(NaverBlock("image", image=path) for path in reviews)
        blocks.append(NaverBlock("text", text=REVIEW_CAPTION))
    if content.tips:
        blocks.append(NaverBlock("text", text=f"“ {tips_heading(content)} ”"))
        blocks.append(NaverBlock("text", text=content.tips))
    blocks.append(NaverBlock("text", text=content.outro))
    if footer is not None:
        blocks.append(NaverBlock("image", image=footer))
    return tuple(blocks)


def extract_post_url(blog_id: str, urls: Sequence[str]) -> str:
    for url in urls:
        if blog_id not in url:
            continue
        match = POST_ID_RE.search(url)
        if match:
            return f"https://blog.naver.com/{blog_id}/{match.group(1)}"
    return ""


def decode_storage_state(encoded: str) -> dict:
    try:
        return json.loads(base64.b64decode(encoded).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise NaverError("NAVER_STORAGE_STATE_B64 값을 해석할 수 없습니다 (base64 JSON 이어야 함)") from exc


class NaverPublisher:
    def __init__(
        self,
        blog_id: str,
        storage_state_b64: str,
        mode: str,
        screenshot_dir: Path,
        selectors: NaverSelectors = NaverSelectors(),
        headless: bool = True,
        on_session_updated: Callable[[str], bool] | None = None,
        write_url: str = WRITE_URL,
        confirm_timeout_s: float = 30.0,
    ) -> None:
        self._confirm_polls = max(1, int(confirm_timeout_s * 2))
        self._blog_id = blog_id
        self._storage_state_b64 = storage_state_b64
        self._mode = mode
        self._screenshot_dir = screenshot_dir
        self._sel = selectors
        self._headless = headless
        self._on_session_updated = on_session_updated
        self._write_url = write_url

    def publish(
        self,
        content: PostContent,
        images_by_stage: Mapping[str, Sequence[Path]],
        header: Path | None = None,
        footer: Path | None = None,
        comparison: Path | None = None,
        reviews: Sequence[Path] = (),
    ) -> PublishResult:
        from playwright.sync_api import sync_playwright

        state = decode_storage_state(self._storage_state_b64)
        blocks = build_blocks(content, images_by_stage, header, footer, comparison, reviews)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=self._headless)
            context = browser.new_context(
                storage_state=state, locale="ko-KR", viewport={"width": 1400, "height": 1000}
            )
            page = context.new_page()
            try:
                url, message = self._write(page, content, blocks)
                self._save_session(context)
                return PublishResult(platform=PLATFORM, ok=True, url=url, message=message)
            except Exception:
                self._screenshot(page, "naver_error")
                raise
            finally:
                context.close()
                browser.close()

    # ----- 내부 단계 -----
    def _write(self, page, content: PostContent, blocks: Sequence[NaverBlock]) -> tuple[str, str]:
        page.goto(self._write_url.format(blog_id=self._blog_id), wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(4000)
        if "nid.naver.com" in page.url or "nidlogin" in page.url:
            raise NaverSessionExpired(
                "네이버 로그인 세션이 만료되었습니다. scripts/export_naver_cookies.py 로 다시 저장하세요"
            )
        editor = page.frame_locator(self._sel.main_frame) if page.locator(self._sel.main_frame).count() else page
        self._dismiss_popups(editor, page)

        editor.locator(self._sel.title).first.click()
        page.keyboard.insert_text(content.title)
        editor.locator(self._sel.body_paragraph).first.click()
        for block in blocks:
            if block.kind == "image" and block.image is not None:
                self._insert_image(page, editor, block.image)
            else:
                self._type_text(page, block.text)
        return self._finish(page, editor, content.hashtags)

    def _dismiss_popups(self, editor, page) -> None:
        for selector in (self._sel.popup_cancel, self._sel.help_close):
            button = editor.locator(selector)
            if button.count():
                try:
                    button.first.click(timeout=3000)
                    page.wait_for_timeout(500)
                except Exception as exc:
                    log.debug("팝업 닫기 무시: %s", exc)

    @staticmethod
    def _type_text(page, text: str) -> None:
        for line in text.split("\n"):
            if line.strip():
                page.keyboard.insert_text(line.strip())
            page.keyboard.press("Enter")

    def _insert_image(self, page, editor, path: Path) -> None:
        before = editor.locator(self._sel.image_component).count()
        with page.expect_file_chooser(timeout=15_000) as chooser:
            editor.locator(self._sel.image_button).first.click()
        chooser.value.set_files(str(path))
        for _ in range(60):
            if editor.locator(self._sel.image_component).count() > before:
                break
            page.wait_for_timeout(500)
        else:
            raise NaverError(f"이미지 업로드가 완료되지 않았습니다: {path.name}")
        page.wait_for_timeout(800)
        editor.locator(self._sel.body_paragraph).last.click()
        page.keyboard.press("End")

    def _finish(self, page, editor, hashtags: Sequence[str]) -> tuple[str, str]:
        if self._mode == "draft":
            editor.locator(self._sel.save_button).first.click()
            page.wait_for_timeout(3000)
            return "", "임시저장 완료 — 네이버 블로그 '임시저장 글'에서 확인 후 발행하세요"

        editor.locator(self._sel.publish_button).first.click()
        page.wait_for_timeout(1500)
        tag_input = editor.locator(self._sel.tag_input).first
        for tag in list(hashtags)[:MAX_TAGS]:
            tag_input.click()
            page.keyboard.insert_text(tag.lstrip("#"))
            page.keyboard.press("Enter")
        editor.locator(self._sel.confirm_publish).first.click()

        for _ in range(self._confirm_polls):
            url = extract_post_url(self._blog_id, [page.url, *(frame.url for frame in page.frames)])
            if url:
                return url, "발행 완료"
            page.wait_for_timeout(500)
        # 발행 버튼까지 눌렀다면 실제로는 게시됐을 가능성이 높다. 실패로 처리하면 수동 초안 안내로
        # 중복 게시가 생길 수 있어, 경고와 함께 성공으로 보고하고 사람이 확인하도록 한다.
        self._screenshot(page, "naver_unconfirmed")
        return (
            f"https://blog.naver.com/{self._blog_id}",
            "⚠️ 발행 버튼은 눌렀지만 게시글 주소를 확인하지 못했습니다. 블로그에서 게시 여부를 확인하세요 "
            "(원고는 드라이브 보관 폴더의 post.txt)",
        )

    def _save_session(self, context) -> None:
        if self._on_session_updated is None:
            return
        try:
            encoded = base64.b64encode(json.dumps(context.storage_state()).encode("utf-8")).decode("ascii")
            self._on_session_updated(encoded)
        except Exception as exc:
            log.warning("네이버 세션 저장 실패 (다음 실행에는 영향 없음): %s", exc)

    def _screenshot(self, page, name: str) -> None:
        try:
            self._screenshot_dir.mkdir(parents=True, exist_ok=True)
            path = self._screenshot_dir / f"{name}_{int(time.time())}.png"
            page.screenshot(path=str(path), full_page=True)
            log.info("네이버 오류 스크린샷 저장: %s", path)
        except Exception as exc:
            log.warning("스크린샷 저장 실패: %s", exc)
