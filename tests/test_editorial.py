import json

import pytest

from autopost.ai_helper import build_prompt, parse_content
from autopost.blog_maintenance import infer_category, post_patch
from autopost.blog_publisher import build_labels
from autopost.editorial import normalize_html, normalize_text
from fakes import ai_json


def test_normalize_html_preserves_images_links_and_attributes():
    markup = '<p>건물 관리 #건물청소 &amp; 상담</p><img src="https://img/건물.jpg" alt="원본"/>'
    markup += '<a href="https://example/건물?q=1>0">건물 안내</a><!-- 건물 --><style>.건물{}</style>'
    result = normalize_html(markup)
    assert '<p>상업 시설 관리 #상업시설청소 &amp; 상담</p>' in result
    assert 'src="https://img/건물.jpg"' in result
    assert 'href="https://example/건물?q=1>0"' in result
    assert '>상업 시설 안내</a>' in result
    assert '<!-- 건물 --><style>.건물{}</style>' in result
    assert normalize_html(result) == result


def test_ai_uses_commercial_facility_terms_in_every_output_field():
    payload = json.loads(ai_json())
    for key in ("title", "intro", "outro", "tips", "tiktok_caption"):
        payload[key] = "건물 관리가 필요합니다."
    payload["hashtags"] = ["건물청소", "건물관리"]
    for section in payload["sections"]:
        section.update(heading="건물 관리", body="건물 청소입니다.", photo_captions=["건물 바닥입니다."])
    content = parse_content(json.dumps(payload), "정기청소", "본연클린")
    assert "건물" not in content.plain_text() + content.tiktok_caption
    assert "상업 시설" in content.intro
    assert "#상업시설청소" in content.hashtags
    prompt = build_prompt("본연클린", "000", "정기청소", {"작업전": 1})
    assert "상업 시설·사무실 정기청소" in prompt


def test_disinfection_has_one_canonical_archive_label():
    labels = build_labels("방역소독", ["#방역소독", "#소독", "#방역"])
    assert labels == ["방역 소독", "소독", "방역"]


def test_existing_post_patch_keeps_metadata_and_other_labels():
    post = {"id": "1", "title": "건물 소독", "content": '<p>건물</p><img src="x"/>',
            "labels": ["방역소독", "지역"], "url": "https://blog/original", "published": "date"}
    patch = post_patch(post)
    assert patch == {"title": "상업 시설 소독", "content": '<p>상업 시설</p><img src="x"/>',
                     "labels": ["방역 소독", "지역"]}
    assert post_patch({**post, **patch}) == {}
    assert post["url"] == "https://blog/original" and post["published"] == "date"


def test_missing_category_can_use_title_but_ambiguous_category_stops():
    assert infer_category({"title": "정기청소 사례"}) == "정기청소"
    with pytest.raises(ValueError):
        infer_category({"labels": ["정기청소", "로프청소"]})
    with pytest.raises(ValueError):
        infer_category({"title": "소개"})


def test_blogger_label_sorting_does_not_trigger_another_update():
    assert post_patch({"title": "정기청소", "content": "상업 시설", "labels": ["지역", "정기청소"]}) == {}


def test_hashtag_replacement_keeps_search_terms_together():
    assert normalize_text("건물 #건물관리") == "상업 시설 #상업시설관리"
