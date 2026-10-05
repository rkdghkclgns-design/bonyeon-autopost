"""구글 드라이브 폴더 구조·카테고리 등 시스템 전역 상수."""
from __future__ import annotations

from dataclasses import dataclass

FOLDER_MIME = "application/vnd.google-apps.folder"

HEADER_FOLDER = "00_공통_헤더이미지"
FOOTER_FOLDER = "00_공통_푸터이미지"
BGM_FOLDER = "00_공통_BGM"
REVIEW_FOLDER = "04_고객후기"
PUBLIC_ASSET_FOLDER = "98_블로그_게시이미지"

HEADER_FILE = "header_로고.png"
FOOTER_FILE = "footer_안내.png"
BGM_FILE = "bgm.mp3"
GUIDE_FILE = "00_사용안내.txt"

STAGE_BEFORE = "작업전"
STAGE_DURING = "작업중"
STAGE_AFTER = "작업후"
STAGES: tuple[str, ...] = (STAGE_BEFORE, STAGE_DURING, STAGE_AFTER)

STAGE_LABELS = {
    STAGE_BEFORE: "작업 전",
    STAGE_DURING: "작업 중",
    STAGE_AFTER: "작업 후",
}

# 출장·상담 가능 범위 — 글의 지역 키워드(검색용)와 별개로 항상 이 문구를 쓴다
SERVICE_AREA = "수도권"
SERVICE_AREA_LINE = f"{SERVICE_AREA} 전 지역 출장·상담 가능합니다."

# 운영 결정: 환경변수나 로그인 정보가 남아 있어도 네이버에는 발행하지 않는다.
NAVER_PUBLISHING_ENABLED = False
NAVER_DISABLED_REASON = "네이버 발행 사용 안 함 (중지됨)"


@dataclass(frozen=True)
class Category:
    folder: str
    name: str


CATEGORIES: tuple[Category, ...] = (
    Category("01_정기청소", "정기청소"),
    Category("02_로프청소", "로프청소"),
    Category("03_방역소독", "방역소독"),
)

# AI 원고 인사말에 쓰는 업종 설명 ("안녕하세요! ○○ 전문 본연클린입니다")
CATEGORY_DESCRIPTIONS = {
    "정기청소": "상업 시설·사무실 정기청소",
    "로프청소": "로프 외벽·간판·유리창 청소",
    "방역소독": "방역·소독",
}

GUIDE_TEXT = """[청소 자동화 사용 안내]

1. 사진 올리기
   - 01_정기청소 / 02_로프청소 / 03_방역소독 폴더 안의
     작업전 / 작업중 / 작업후 폴더에 현장 사진을 올려주세요.
   - 한 번 포스팅에 폴더별 최대 3장(기본값)이 사용됩니다. 사진은 옮기지 않고 그대로 둡니다.
   - 새로 올린 사진이 먼저(올린 순서대로) 쓰이고, 다 쓴 뒤에는 이미 쓴 사진을 덜 쓴 순서로
     섞어 매번 다른 조합으로 다시 씁니다. (다시 쓴 글은 '작업 사례' 글로 작성)
   - 필요 없어진 사진은 이 폴더에서 지우면 더 이상 쓰이지 않습니다.

2. 공통 이미지 교체
   - 00_공통_헤더이미지/header_로고.png : 블로그 맨 위 로고
   - 00_공통_푸터이미지/footer_안내.png : 블로그 맨 아래 연락처 안내 (틱톡 영상 마지막 장면)
   - 00_공통_BGM/bgm.mp3 : 틱톡 영상 배경음악 (저작권 없는 음원만 사용하세요)
   파일 이름을 그대로 유지한 채 내용만 바꿔 올리면 됩니다.

3. 04_고객후기 (선택)
   - 고객님께 게시 동의를 받은 '실제' 후기 캡처(카톡·문자·네이버 리뷰 등)만 올려주세요.
   - 이름·전화번호·주소 등 개인정보는 반드시 가린 뒤 올려주세요.
   - 포스팅마다 1장씩 글 끝에 들어갑니다 (덜 쓴 후기부터 돌아가며 사용).

4. 98_블로그_게시이미지 폴더는 블로그 이미지 호스팅용입니다. 삭제하지 마세요.
"""

REVIEW_HEADING = "고객님이 남겨주신 후기"
REVIEW_CAPTION = "실제 고객님께서 남겨주신 후기입니다 (게시 동의를 받았습니다)"
