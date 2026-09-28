import base64
import json
from pathlib import Path

import pytest

from autopost.ai_helper import parse_content
from autopost.naver_publisher import (
    MAX_SECRET_CHARS,
    NaverError,
    NaverPublisher,
    build_blocks,
    decode_storage_state,
    encode_storage_state,
    extract_post_url,
)
from fakes import ai_json


def test_build_blocks_order():
    content = parse_content(ai_json(), "로프청소", "본연")
    blocks = build_blocks(
        content,
        {"작업전": [Path("b1.jpg")], "작업후": [Path("a1.jpg"), Path("a2.jpg")]},
        header=Path("header.png"),
        footer=Path("footer.png"),
    )
    summary = [(b.kind, b.image.name if b.image else b.text[:6]) for b in blocks]
    assert summary[0] == ("image", "header.png")
    assert summary[-1] == ("image", "footer.png")
    assert ("image", "b1.jpg") in summary
    kinds = [b.kind for b in blocks]
    assert kinds.count("image") == 5
    # 소제목 → 도입 문장 → 사진 → 그 사진 설명 순서
    before_idx = next(i for i, b in enumerate(blocks) if b.text.startswith("“ 작업전"))
    assert blocks[before_idx + 1].text == "작업전 설명입니다."
    assert blocks[before_idx + 2].image == Path("b1.jpg")
    assert blocks[before_idx + 3].text == "작업전 첫 사진 설명"


def test_build_blocks_adds_comparison_reviews_tips_before_outro():
    content = parse_content(ai_json(title="[수원 로프청소] 현장"), "로프청소", "본연")
    blocks = build_blocks(
        content, {"작업후": [Path("a.jpg")]}, comparison=Path("cmp.jpg"), reviews=[Path("rv.jpg")]
    )
    idx = next(i for i, b in enumerate(blocks) if b.image == Path("cmp.jpg"))
    texts_after = [b.text or b.image.name for b in blocks[idx + 1:]]
    assert texts_after[:7] == [
        "작업 전(좌) · 작업 후(우)",
        "“ 고객님이 남겨주신 후기 ”",
        "rv.jpg",
        "실제 고객님께서 남겨주신 후기입니다 (게시 동의를 받았습니다)",
        "“ 수원 로프청소 관리 TIP ”",
        "간판은 6개월마다 점검하면 좋아요.",
        content.outro,
    ]


def test_build_blocks_without_assets():
    content = parse_content(ai_json(stages=("작업후",)), "로프청소", "본연")
    blocks = build_blocks(content, {"작업후": [Path("a.jpg")]})
    assert blocks[0].kind == "text" and blocks[-1].kind == "text"


@pytest.mark.parametrize("urls,expected", [
    (["https://blog.naver.com/myblog/223456789012"], "https://blog.naver.com/myblog/223456789012"),
    (["https://blog.naver.com/PostView.naver?blogId=myblog&logNo=223456789012"],
     "https://blog.naver.com/myblog/223456789012"),
    (["https://blog.naver.com/myblog/postwrite", "about:blank"], ""),
    (["https://blog.naver.com/other/223456789012"], ""),
])
def test_extract_post_url(urls, expected):
    assert extract_post_url("myblog", urls) == expected


def test_decode_storage_state_roundtrip_and_error():
    state = {"cookies": [{"name": "NID_AUT", "value": "x"}], "origins": []}
    encoded = base64.b64encode(json.dumps(state).encode()).decode()
    assert decode_storage_state(encoded) == state
    with pytest.raises(NaverError):
        decode_storage_state("!!!not-base64!!!")


def test_encode_storage_state_keeps_only_naver_data():
    state = {
        "cookies": [
            {"name": "NID_AUT", "value": "a", "domain": ".naver.com"},
            {"name": "blog", "value": "b", "domain": "blog.naver.com"},
            {"name": "ad", "value": "c", "domain": ".doubleclick.net"},
            {"name": "trick", "value": "d", "domain": "naver.com.evil.io"},
        ],
        "origins": [
            {"origin": "https://blog.naver.com", "localStorage": [{"name": "k", "value": "v"}]},
            {"origin": "https://tracker.example", "localStorage": []},
        ],
    }
    decoded = decode_storage_state(encode_storage_state(state))
    assert [c["name"] for c in decoded["cookies"]] == ["NID_AUT", "blog"]
    assert [o["origin"] for o in decoded["origins"]] == ["https://blog.naver.com"]


def test_encode_storage_state_drops_origins_when_too_large_for_secret():
    state = {
        "cookies": [{"name": "NID_SES", "value": "s", "domain": ".naver.com"}],
        "origins": [{"origin": "https://blog.naver.com", "localStorage": [{"name": "big", "value": "x" * 60_000}]}],
    }
    encoded = encode_storage_state(state)
    assert len(encoded) <= MAX_SECRET_CHARS
    assert decode_storage_state(encoded) == {"cookies": state["cookies"], "origins": []}


def test_publisher_defers_decoding_until_publish(tmp_path):
    # 잘못된 세션 값이어도 생성 단계에서는 실패하지 않아야 다른 플랫폼 발행이 계속된다
    NaverPublisher("myblog", "invalid", "publish", tmp_path)
