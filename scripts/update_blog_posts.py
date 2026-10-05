"""기존 글의 시설 명칭·자료실 분류를 맞춘다. 기본은 점검, --apply 때만 수정."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from autopost.blog_maintenance import post_patch  # noqa: E402
from autopost.cli import _load_dotenv  # noqa: E402
from autopost.config import load_config  # noqa: E402
from autopost.google_auth import build_blogger_service, build_credentials  # noqa: E402


def list_posts(service, blog_id: str) -> list[dict]:
    posts: dict[str, dict] = {}
    for status in ("LIVE", "DRAFT", "SCHEDULED"):
        page_token = None
        while True:
            response = service.posts().list(
                blogId=blog_id, status=status, fetchBodies=True, maxResults=100, pageToken=page_token,
            ).execute(num_retries=3)
            for post in response.get("items", []):
                posts[post["id"]] = post
            page_token = response.get("nextPageToken")
            if not page_token:
                break
    return list(posts.values())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="원본을 백업한 뒤 기존 글에 반영")
    args = parser.parse_args()
    _load_dotenv()
    cfg = load_config()
    if not (cfg.google and cfg.blogger_blog_id):
        raise SystemExit("Google 인증과 BLOGGER_BLOG_ID가 필요합니다")
    service = build_blogger_service(build_credentials(cfg.google))
    posts = list_posts(service, cfg.blogger_blog_id)
    changes = [(post, post_patch(post)) for post in posts]
    changes = [(post, patch) for post, patch in changes if patch]
    for post, patch in changes:
        print(f"{post['id']} | {post['title']} | 수정: {', '.join(patch)}")
    print(f"전체 {len(posts)}개 / 수정 대상 {len(changes)}개")
    if not args.apply or not changes:
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_dir = cfg.output_dir / "blog_maintenance" / stamp
    backup_dir.mkdir(parents=True, exist_ok=False)
    (backup_dir / "original_posts.json").write_text(
        json.dumps(posts, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    (backup_dir / "changes.json").write_text(
        json.dumps([{ "id": post["id"], "patch": patch } for post, patch in changes],
                   ensure_ascii=False, indent=2), encoding="utf-8",
    )
    verified = []
    for original, patch in changes:
        latest = service.posts().get(blogId=cfg.blogger_blog_id, postId=original["id"]).execute(num_retries=3)
        if any(latest.get(key) != original.get(key) for key in ("title", "content", "labels", "updated")):
            raise RuntimeError(f"글 {original['id']}이 점검 이후 변경되어 중단합니다")
        service.posts().patch(blogId=cfg.blogger_blog_id, postId=original["id"], body=patch).execute(num_retries=3)
        result = service.posts().get(blogId=cfg.blogger_blog_id, postId=original["id"]).execute(num_retries=3)
        if post_patch(result) or any(result.get(key) != original.get(key) for key in ("url", "published")):
            raise RuntimeError(f"글 {original['id']} 수정 후 검증 실패")
        verified.append({"id": result["id"], "url": result.get("url"), "title": result["title"],
                         "labels": result.get("labels", [])})
        (backup_dir / "verified.json").write_text(
            json.dumps(verified, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        print(f"수정 확인: {result['id']} | {result['title']}")
    print(f"수정 완료 {len(verified)}개 / 원본 백업: {backup_dir.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
