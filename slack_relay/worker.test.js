// node --test  (Node 18+ : 전역 crypto.subtle / fetch / Request / Response 사용)
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import worker, { parseText, sign, verifySlackSignature } from "./worker.js";

const SECRET = "test-signing-secret";
const ENV = { SLACK_SIGNING_SECRET: SECRET, GITHUB_TOKEN: "ghp_x", GITHUB_REPO: "me/repo" };
const realFetch = globalThis.fetch;
let dispatched;

beforeEach(() => {
  dispatched = [];
  globalThis.fetch = async (url, init) => {
    dispatched.push({ url, init, body: JSON.parse(init.body) });
    return new Response(null, { status: 204 });
  };
});

afterEach(() => {
  globalThis.fetch = realFetch;
});

async function slackRequest(params, { secret = SECRET, timestamp = Math.floor(Date.now() / 1000) } = {}) {
  const body = new URLSearchParams(params).toString();
  const signature = await sign(secret, `v0:${timestamp}:${body}`);
  return new Request("https://relay.example/", {
    method: "POST",
    headers: { "X-Slack-Request-Timestamp": String(timestamp), "X-Slack-Signature": signature },
    body,
  });
}

test("parseText extracts category and dry-run flag", () => {
  assert.deepEqual(parseText("로프청소 테스트"), { category: "로프청소", dryRun: true });
  assert.deepEqual(parseText("  "), { category: "", dryRun: false });
  assert.deepEqual(parseText("DRY-RUN 방역"), { category: "방역", dryRun: true });
});

test("parseText strips slack mrkdwn control characters", () => {
  assert.deepEqual(parseText("```<!channel> 로프"), { category: "channel 로프", dryRun: false });
});

test("signature verification rejects tampering and stale requests", async () => {
  const ts = "1700000000";
  const good = await sign(SECRET, `v0:${ts}:a=1`);
  const headers = (sig, t = ts) => new Headers({ "X-Slack-Request-Timestamp": t, "X-Slack-Signature": sig });
  assert.equal(await verifySlackSignature(headers(good), "a=1", SECRET, 1700000000), true);
  assert.equal(await verifySlackSignature(headers(good), "a=2", SECRET, 1700000000), false);
  assert.equal(await verifySlackSignature(headers(good), "a=1", SECRET, 1700000000 + 600), false);
  assert.equal(await verifySlackSignature(headers(good), "a=1", "", 1700000000), false);
});

test("valid /posting command dispatches slack-post with payload", async () => {
  const request = await slackRequest({ command: "/posting", text: "로프청소", user_id: "U1", user_name: "hong" });
  const response = await worker.fetch(request, ENV);
  const json = await response.json();
  assert.equal(json.response_type, "in_channel");
  assert.equal(dispatched.length, 1);
  assert.equal(dispatched[0].url, "https://api.github.com/repos/me/repo/dispatches");
  assert.deepEqual(dispatched[0].body, {
    event_type: "slack-post",
    client_payload: { category: "로프청소", dry_run: false, requested_by: "hong" },
  });
});

test("korean setup command maps to slack-setup", async () => {
  const response = await worker.fetch(await slackRequest({ command: "/초기세팅", user_id: "U1" }), ENV);
  assert.equal(response.status, 200);
  assert.equal(dispatched[0].body.event_type, "slack-setup");
});

test("bad signature returns 401 and does not dispatch", async () => {
  const response = await worker.fetch(await slackRequest({ command: "/posting" }, { secret: "wrong" }), ENV);
  assert.equal(response.status, 401);
  assert.equal(dispatched.length, 0);
});

test("user allowlist is enforced", async () => {
  const env = { ...ENV, ALLOWED_USER_IDS: "U9, U8" };
  const response = await worker.fetch(await slackRequest({ command: "/posting", user_id: "U1" }), env);
  assert.match((await response.json()).text, /권한/);
  assert.equal(dispatched.length, 0);
});

test("unknown command and GitHub failure are reported ephemerally", async () => {
  const unknown = await worker.fetch(await slackRequest({ command: "/hack" }), ENV);
  assert.match((await unknown.json()).text, /알 수 없는 명령어/);

  globalThis.fetch = async () => new Response("nope", { status: 404 });
  const failed = await worker.fetch(await slackRequest({ command: "/posting" }), ENV);
  const json = await failed.json();
  assert.equal(json.response_type, "ephemeral");
  assert.match(json.text, /HTTP 404/);
});

test("GET health check", async () => {
  const response = await worker.fetch(new Request("https://relay.example/"), ENV);
  assert.equal(await response.text(), "ok");
});
