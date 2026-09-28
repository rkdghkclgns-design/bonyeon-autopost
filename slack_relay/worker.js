/**
 * 슬랙 슬래시 커맨드 → GitHub Actions(repository_dispatch) 중계 Cloudflare Worker.
 *
 * GitHub Actions 는 외부 요청(웹훅)을 직접 받을 수 없어서, 슬랙 명령을 이 Worker 가 받아
 * 서명 검증 후 GitHub API 로 워크플로를 실행시킨다. (Cloudflare 무료 플랜으로 충분)
 *
 * 필요한 설정 (wrangler secret put / wrangler.toml [vars])
 *   SLACK_SIGNING_SECRET : 슬랙 앱 > Basic Information > Signing Secret
 *   GITHUB_TOKEN         : fine-grained PAT (대상 리포지토리 Contents: Read and write)
 *   GITHUB_REPO          : "깃허브아이디/리포지토리명"
 *   ALLOWED_USER_IDS     : (선택) 실행 허용 슬랙 사용자 ID 목록 "U0123,U0456"
 *
 * 사용 예:  /posting            → 자동 카테고리로 포스팅
 *           /posting 로프청소   → 카테고리 지정
 *           /posting 테스트     → 발행 없이 원고·영상 미리보기(dry-run)
 *           /posting-setup      → 초기 세팅 점검
 */

export const COMMANDS = {
  "/posting": "slack-post",
  "/포스팅": "slack-post",
  "/posting-setup": "slack-setup",
  "/초기세팅": "slack-setup",
};

const MAX_AGE_SECONDS = 60 * 5;
const DRY_RUN_WORDS = /(테스트|dry-?run|test)/gi;

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("ok");
    }
    const raw = await request.text();
    if (!(await verifySlackSignature(request.headers, raw, env.SLACK_SIGNING_SECRET))) {
      return new Response("invalid signature", { status: 401 });
    }

    const form = new URLSearchParams(raw);
    const command = form.get("command") || "";
    const eventType = COMMANDS[command];
    if (!eventType) {
      return reply(`알 수 없는 명령어입니다: ${command}`);
    }

    const userId = form.get("user_id") || "";
    const allowed = (env.ALLOWED_USER_IDS || "").split(",").map((s) => s.trim()).filter(Boolean);
    if (allowed.length > 0 && !allowed.includes(userId)) {
      return reply("이 명령어를 실행할 권한이 없습니다. 관리자에게 문의하세요.");
    }

    const { category, dryRun } = parseText(form.get("text") || "");
    const payload = { category, dry_run: dryRun, requested_by: form.get("user_name") || userId };
    try {
      await dispatch(env, eventType, payload);
    } catch (err) {
      return reply(`GitHub Actions 실행 요청에 실패했습니다: ${err.message}`);
    }

    const label = eventType === "slack-setup"
      ? "초기 세팅"
      : `포스팅${category ? ` (${category})` : ""}${dryRun ? " [테스트]" : ""}`;
    return reply(`🧹 ${label} 요청을 접수했습니다. 몇 분 안에 이 채널로 결과를 알려드릴게요.`, "in_channel");
  },
};

export function parseText(text) {
  const dryRun = new RegExp(DRY_RUN_WORDS.source, "i").test(text);
  const category = text
    .replace(DRY_RUN_WORDS, "")
    .replace(/[`<>&*_~|!]/g, "") // 슬랙 mrkdwn 제어문자 제거 (멘션·코드블록 탈출 방지)
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 30);
  return { category, dryRun };
}

export async function verifySlackSignature(headers, body, secret, nowSeconds = Date.now() / 1000) {
  const timestamp = headers.get("X-Slack-Request-Timestamp");
  const signature = headers.get("X-Slack-Signature");
  if (!secret || !timestamp || !signature) {
    return false;
  }
  if (Math.abs(nowSeconds - Number(timestamp)) > MAX_AGE_SECONDS) {
    return false; // 재전송(replay) 공격 방지
  }
  const expected = await sign(secret, `v0:${timestamp}:${body}`);
  return timingSafeEqual(expected, signature);
}

export async function sign(secret, message) {
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw", encoder.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"],
  );
  const mac = await crypto.subtle.sign("HMAC", key, encoder.encode(message));
  return "v0=" + [...new Uint8Array(mac)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function timingSafeEqual(a, b) {
  if (a.length !== b.length) {
    return false;
  }
  let diff = 0;
  for (let i = 0; i < a.length; i += 1) {
    diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return diff === 0;
}

async function dispatch(env, eventType, payload) {
  if (!env.GITHUB_TOKEN || !env.GITHUB_REPO) {
    throw new Error("Worker 에 GITHUB_TOKEN / GITHUB_REPO 가 설정되지 않았습니다");
  }
  const response = await fetch(`https://api.github.com/repos/${env.GITHUB_REPO}/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "cleaning-autopost-slack-relay",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ event_type: eventType, client_payload: payload }),
  });
  if (response.status !== 204) {
    throw new Error(`GitHub API HTTP ${response.status}`);
  }
}

function reply(text, responseType = "ephemeral") {
  return new Response(JSON.stringify({ response_type: responseType, text }), {
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}
