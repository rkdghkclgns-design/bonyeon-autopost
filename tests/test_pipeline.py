from dataclasses import replace
from datetime import datetime

import pytest

from autopost import setup_engine, templates
from autopost.ai_helper import parse_content
from autopost.config import load_config
from autopost.constants import USED_FOLDER
from autopost.pipeline import KST, RunOptions, Services, run_post, run_setup, safe_name
from autopost.results import PublishResult
from autopost.slack_helper import SlackNotifier
from fakes import FakeWebClient, MemoryDrive, ai_json, jpeg_bytes

ROOT = "자동화루트"
FIXED_NOW = datetime(2026, 9, 28, 10, 0, tzinfo=KST)


class FakeGenerator:
    def __init__(self):
        self.calls = []
        self.areas = []

    def generate(self, category, images_by_stage, area=None):
        self.calls.append((category, {k: list(v) for k, v in images_by_stage.items()}))
        self.areas.append(area)
        return parse_content(ai_json(), category, "본연", area=area)


class FakeBlogger:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def publish(self, title, html_body, labels):
        if self.error:
            raise self.error
        self.calls.append((title, html_body, labels))
        return PublishResult("구글 블로그", True, url="https://blog/post", message="발행 완료")


class FakePublisher:
    def __init__(self, platform, error=None):
        self.platform = platform
        self.error = error
        self.calls = []

    def publish(self, *args):
        self.calls.append(args)
        if self.error:
            raise self.error
        return PublishResult(self.platform, True, url=f"https://{self.platform}/1")


def fake_video(slides, out_path, bgm_path=None, total_seconds=15.0):
    fake_video.calls.append((list(slides), bgm_path, total_seconds))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(b"mp4")
    return out_path


fake_video.calls = []


@pytest.fixture(autouse=True)
def fast_templates(monkeypatch):
    def fake(path, *args, **kwargs):
        path.write_bytes(jpeg_bytes())
        return path

    for name in ("generate_header", "generate_footer", "generate_bgm"):
        monkeypatch.setattr(templates, name, fake)
    fake_video.calls = []


@pytest.fixture
def world(tmp_path):
    drive = MemoryDrive()
    layout = setup_engine.ensure_layout(drive, ROOT, "본연", "010").layout
    photos = {
        stage: [drive.add_file(layout.stage_folders["로프청소"][stage], f"{stage}_{i}.jpg", jpeg_bytes())
                for i in range(count)]
        for stage, count in (("작업전", 2), ("작업중", 1), ("작업후", 2))
    }
    cfg = load_config({
        "COMPANY_NAME": "본연", "DRIVE_ROOT_FOLDER_NAME": ROOT, "OUTPUT_DIR": str(tmp_path / "out"),
        "GEMINI_API_KEY": "g",
    })
    client = FakeWebClient()
    return drive, layout, photos, cfg, client


def _services(drive, client, **kwargs):
    return Services(
        drive=drive,
        slack=SlackNotifier(channel_id="C1", client=client),
        generator=kwargs.pop("generator", FakeGenerator()),
        video_maker=fake_video,
        now=lambda: FIXED_NOW,
        **kwargs,
    )


def _archive_children(drive, layout):
    archive = drive.find_child(layout.used_folder_id, "2026-09-28_1000_로프청소", folder_only=True)
    return archive, ([c.name for c in drive.children(archive.id)] if archive else [])


def test_full_success_publishes_everywhere_and_archives(world):
    drive, layout, photos, cfg, client = world
    blogger = FakeBlogger()
    naver = FakePublisher("네이버 블로그")
    tiktok = FakePublisher("틱톡")
    generator = FakeGenerator()

    code = run_post(cfg, RunOptions(trigger="schedule"), _services(
        drive, client, generator=generator, blogger=blogger, naver=naver, tiktok=tiktok))

    assert code == 0
    category, images = generator.calls[0]
    assert category == "로프청소"
    assert {k: len(v) for k, v in images.items()} == {"작업전": 2, "작업중": 1, "작업후": 2}

    title, html_body, labels = blogger.calls[0]
    assert html_body.count("lh3.googleusercontent.com") == 5 + 1 + 2  # 사진 5 + 전후비교 + 헤더/푸터
    assert "작업 전(좌) · 작업 후(우)" in html_body
    assert "작업후 첫 사진 설명" in html_body
    assert labels[0] == "로프청소"
    assert len(drive.public) == 8

    slides, bgm_path, seconds = fake_video.calls[0]
    assert len(slides) == 5 + 2  # 사진 5 + 전후비교 + 푸터
    assert slides[0].label == "본연 | 작업 전"
    assert slides[-2].label == "본연 | 작업 전 · 후" and slides[-1].label == ""
    assert bgm_path is not None and seconds == 15.0

    archive, names = _archive_children(drive, layout)
    assert drive.path_of(archive.id) == f"{ROOT}/{USED_FOLDER}/2026-09-28_1000_로프청소"
    assert {"tiktok.mp4", "post.txt"} <= set(names)
    for ids in photos.values():
        assert all(drive.items[i]["parent"] == archive.id for i in ids)

    texts = client.texts()
    assert any("포스팅 가동 중" in t for t in texts)
    assert not any("수동 발행용" in t for t in texts)
    assert client.uploads == []
    report = client.messages[-1]["blocks"]
    assert any("✅ *틱톡*" in b.get("text", {}).get("text", "") for b in report)


def test_partial_failure_sends_manual_fallbacks(world):
    drive, layout, photos, cfg, client = world
    code = run_post(cfg, RunOptions(category="로프"), _services(
        drive, client, blogger=FakeBlogger(),
        naver=FakePublisher("네이버 블로그", RuntimeError("selector not found")),
        tiktok=FakePublisher("틱톡", RuntimeError("spam risk"))))

    assert code == 0
    assert any("네이버 블로그 수동 발행용 초안" in t for t in client.texts())
    assert client.uploads and client.uploads[0]["title"] == "틱톡 영상"
    _, names = _archive_children(drive, layout)
    assert names  # 1곳이라도 성공 → 사진 이동


def test_all_failed_keeps_photos_for_retry(world):
    drive, layout, photos, cfg, client = world
    code = run_post(cfg, RunOptions(), _services(drive, client, blogger=FakeBlogger(RuntimeError("401"))))

    assert code == 1
    archive, _ = _archive_children(drive, layout)
    assert archive is None
    first = photos["작업전"][0]
    assert drive.items[first]["parent"] == layout.stage_folders["로프청소"]["작업전"]
    report = "\n".join(b.get("text", {}).get("text", "") for b in client.messages[-1]["blocks"])
    assert "❌ *구글 블로그*\n401" in report
    assert "⏭️ *네이버 블로그*" in report


def test_review_is_published_and_archived_and_area_rotates(world):
    drive, layout, photos, cfg, client = world
    review = drive.add_file(layout.review_folder_id, "후기1.jpg", jpeg_bytes())
    drive.add_file(layout.review_folder_id, "후기2.jpg", jpeg_bytes())  # REVIEWS_PER_POST=1 → 다음 글에 사용
    cfg = replace(cfg, service_areas=("안산",))
    blogger = FakeBlogger()
    naver = FakePublisher("네이버 블로그")
    generator = FakeGenerator()

    assert run_post(cfg, RunOptions(), _services(drive, client, generator=generator, blogger=blogger, naver=naver)) == 0

    area = generator.areas[0]
    assert area.city == "안산" and not area.is_site  # 서비스 지역 키워드 (현장 위치 아님)
    assert any("📍 지역 키워드: 안산" in t and "(서비스 지역)" in t for t in client.texts())
    html_body = blogger.calls[0][1]
    assert "고객님이 남겨주신 후기" in html_body
    assert html_body.count("lh3.googleusercontent.com") == 5 + 1 + 1 + 2  # 사진+비교+후기+헤더/푸터
    naver_reviews = naver.calls[0][5]
    assert len(naver_reviews) == 1
    archive, names = _archive_children(drive, layout)
    assert drive.items[review]["parent"] == archive.id
    assert len(drive.list_images(layout.review_folder_id)) == 1


def test_actual_site_location_overrides_rotation(world):
    drive, layout, photos, cfg, client = world
    generator = FakeGenerator()
    cfg = replace(cfg, service_areas=("서울",))
    run_post(cfg, RunOptions(location="고잔동"), _services(drive, client, generator=generator, blogger=FakeBlogger()))
    assert generator.areas[0].is_site and generator.areas[0].label == "안산 단원구 고잔동"


def test_no_area_when_not_configured(world):
    drive, layout, photos, cfg, client = world
    generator = FakeGenerator()
    run_post(cfg, RunOptions(), _services(drive, client, generator=generator, blogger=FakeBlogger()))
    assert generator.areas == [None]


def test_no_comparison_without_after_photos_and_video_caps_per_stage(tmp_path):
    drive = MemoryDrive()
    layout = setup_engine.ensure_layout(drive, ROOT, "본연", "010").layout
    for i in range(5):
        drive.add_file(layout.stage_folders["정기청소"]["작업전"], f"b{i}.jpg", jpeg_bytes())
    cfg = load_config({"DRIVE_ROOT_FOLDER_NAME": ROOT, "OUTPUT_DIR": str(tmp_path), "PHOTOS_PER_STAGE": "5"})
    blogger = FakeBlogger()
    assert run_post(cfg, RunOptions(), _services(drive, FakeWebClient(), blogger=blogger)) == 0
    assert "전후 비교" not in blogger.calls[0][1]
    slides = fake_video.calls[0][0]
    assert len(slides) == 3 + 1  # 영상은 단계별 최대 3장 + 푸터


def test_video_failure_only_fails_tiktok(world):
    drive, layout, photos, cfg, client = world
    blogger = FakeBlogger()
    naver = FakePublisher("네이버 블로그")
    tiktok = FakePublisher("틱톡")

    def broken_video(*args, **kwargs):
        raise RuntimeError("ffmpeg crashed")

    services = replace(_services(drive, client, blogger=blogger, naver=naver, tiktok=tiktok), video_maker=broken_video)
    code = run_post(cfg, RunOptions(), services)

    assert code == 0
    assert blogger.calls and naver.calls
    assert tiktok.calls == []
    report = "\n".join(b.get("text", {}).get("text", "") for b in client.messages[-1]["blocks"])
    assert "❌ *틱톡*\n영상 생성 실패: ffmpeg crashed" in report
    assert client.uploads == []  # 업로드할 영상이 없음
    archive, names = _archive_children(drive, layout)
    assert archive is not None and "tiktok.mp4" not in names


def test_partial_move_failure_still_reports_results(world):
    drive, layout, photos, cfg, client = world
    stuck = photos["작업후"][0]
    original_move = drive.move

    def flaky_move(file_id, new_parent_id):
        if file_id == stuck:
            raise RuntimeError("Drive 503")
        original_move(file_id, new_parent_id)

    drive.move = flaky_move
    code = run_post(cfg, RunOptions(), _services(drive, client, blogger=FakeBlogger()))

    assert code == 0
    archive, _ = _archive_children(drive, layout)
    moved = [i for ids in photos.values() for i in ids if drive.items[i]["parent"] == archive.id]
    assert len(moved) == 4
    report = "\n".join(b.get("text", {}).get("text", "") for b in client.messages[-1]["blocks"])
    assert "사진 1장 이동 실패" in report
    assert "✅ *구글 블로그*" in report


def test_archive_folder_failure_still_reports_results(world):
    drive, layout, photos, cfg, client = world
    services = _services(drive, client, blogger=FakeBlogger())
    original_ensure = drive.ensure_folder

    def failing_ensure(parent_id, name):
        if parent_id == layout.used_folder_id:
            raise RuntimeError("quota")
        return original_ensure(parent_id, name)

    drive.ensure_folder = failing_ensure
    assert run_post(cfg, RunOptions(), services) == 0
    report = "\n".join(b.get("text", {}).get("text", "") for b in client.messages[-1]["blocks"])
    assert "사진 5장 이동 실패" in report


def test_dry_run_publishes_nothing_but_sends_preview(world):
    drive, layout, photos, cfg, client = world
    blogger = FakeBlogger()
    code = run_post(cfg, RunOptions(dry_run=True), _services(drive, client, blogger=blogger))

    assert code == 0
    assert blogger.calls == []
    assert _archive_children(drive, layout)[0] is None
    assert any("수동 발행용 초안" in t for t in client.texts())
    assert client.uploads
    assert "테스트" in client.messages[-1]["blocks"][0]["text"]["text"]


def test_not_enough_photos(world, tmp_path):
    drive, layout, photos, cfg, client = world
    code = run_post(cfg, RunOptions(category="방역소독"), _services(drive, client, blogger=FakeBlogger()))
    assert code == 0
    assert any("사진이 부족합니다" in t for t in client.texts())


def test_unknown_category(world):
    drive, layout, photos, cfg, client = world
    code = run_post(cfg, RunOptions(category="입주청소"), _services(drive, client, blogger=FakeBlogger()))
    assert code == 1
    assert any("알 수 없는 카테고리" in t for t in client.texts())


def test_self_setup_runs_when_structure_missing(tmp_path):
    drive = MemoryDrive()
    client = FakeWebClient()
    cfg = load_config({"DRIVE_ROOT_FOLDER_NAME": ROOT, "OUTPUT_DIR": str(tmp_path)})
    code = run_post(cfg, RunOptions(), _services(drive, client, blogger=FakeBlogger()))
    assert code == 0
    assert any("셀프 세팅" in t for t in client.texts())
    assert drive.find_child("root", ROOT) is not None


def test_run_setup_reports_to_slack(world):
    drive, layout, photos, cfg, client = world
    assert run_setup(cfg, Services(drive=drive, slack=SlackNotifier(channel_id="C1", client=client))) == 0
    message = client.messages[-1]
    assert message["text"].startswith("✅")
    assert "변경 없음" in message["blocks"][1]["text"]["text"]


def test_run_post_requires_generator(world):
    drive, layout, photos, cfg, client = world
    with pytest.raises(RuntimeError):
        run_post(cfg, RunOptions(), Services(drive=drive, slack=SlackNotifier()))


@pytest.mark.parametrize("name,expected", [
    ("작업 전 1.jpg", "작업_전_1.jpg"), ('a/b:c*?"<>|.jpg', "a_b_c_.jpg"), ("///", "file"),
])
def test_safe_name(name, expected):
    assert safe_name(name) == expected
