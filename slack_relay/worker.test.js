// node --test  (Node 18+ : 전역 crypto.subtle / fetch / Request / Response 사용)
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import worker, { buildInputs, dispatchUrl, parseText, sign, verifySlackSignature } from "./worker.js";

const SECRET = "test-signing-secret";
const ENV = { SLACK_SIGNING_SECRET: SECRET, GITHUB_TOKEN: "ghp_x", GITHUB_REPO: "me/repo" };
const DISPATCH_URL = "https://api.github.com/repos/me/repo/actions/workflows/auto_post.yml/dispatches";
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
  assert.deepEqual(parseText("정기청소 고잔동"), { category: "정기청소 고잔동", dryRun: false });
});

test("parseText strips slack mrkdwn control characters and quotes", () => {
  assert.deepEqual(parseText("```<!channel> 로프"), { category: "channel 로프", dryRun: false });
  assert.deepEqual(parseText(`"정기"'청소'\\`), { category: "정기청소", dryRun: false });
});

test("buildInputs sends string inputs and ignores category/dry-run for setup", () => {
  assert.deepEqual(buildInputs("post", "로프청소", true, "hong"), {
    mode: "post", category: "로프청소", location: "", dry_run: "true", source: "slack", requested_by: "hong",
  });
  assert.deepEqual(buildInputs("setup", "로프청소", true, "hong"), {
    mode: "setup", category: "", location: "", dry_run: "false", source: "slack", requested_by: "hong",
  });
});

test("dispatchUrl honours custom workflow file", () => {
  assert.equal(dispatchUrl(ENV), DISPATCH_URL);
  assert.equal(
    dispatchUrl({ ...ENV, GITHUB_WORKFLOW: "other.yml" }),
    "https://api.github.com/repos/me/repo/actions/workflows/other.yml/dispatches",
  );
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

test("valid /posting command dispatches the workflow with inputs", async () => {
  const request = await slackRequest({ command: "/posting", text: "로프청소 테스트", user_id: "U1", user_name: "hong" });
  const response = await worker.fetch(request, ENV);
  const json = await response.json();
  assert.equal(json.response_type, "in_channel");
  assert.match(json.text, /로프청소.*테스트/);
  assert.equal(dispatched.length, 1);
  assert.equal(dispatched[0].url, DISPATCH_URL);
  assert.match(dispatched[0].init.headers.Authorization, /^Bearer ghp_x$/);
  assert.deepEqual(dispatched[0].body, {
    ref: "main",
    inputs: {
      mode: "post", category: "로프청소", location: "", dry_run: "true", source: "slack", requested_by: "hong",
    },
  });
});

test("custom ref is used when configured", async () => {
  await worker.fetch(await slackRequest({ command: "/posting", user_id: "U1" }), { ...ENV, GITHUB_REF: "dev" });
  assert.equal(dispatched[0].body.ref, "dev");
});

test("korean setup command maps to setup mode", async () => {
  const response = await worker.fetch(await slackRequest({ command: "/초기세팅", user_id: "U1" }), ENV);
  assert.equal(response.status, 200);
  assert.equal(dispatched[0].body.inputs.mode, "setup");
});

test("help text is returned without dispatching", async () => {
  for (const text of ["도움말", "help", "?"]) {
    const response = await worker.fetch(await slackRequest({ command: "/posting", text, user_id: "U1" }), ENV);
    const json = await response.json();
    assert.equal(json.response_type, "ephemeral");
    assert.match(json.text, /명령어/);
  }
  assert.equal(dispatched.length, 0);
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

test("unknown command, missing config and GitHub failure are reported ephemerally", async () => {
  const unknown = await worker.fetch(await slackRequest({ command: "/hack" }), ENV);
  assert.match((await unknown.json()).text, /알 수 없는 명령어/);

  const noToken = await worker.fetch(await slackRequest({ command: "/posting" }), { ...ENV, GITHUB_TOKEN: "" });
  assert.match((await noToken.json()).text, /GITHUB_TOKEN/);

  globalThis.fetch = async () => new Response("nope", { status: 404 });
  const failed = await worker.fetch(await slackRequest({ command: "/posting" }), ENV);
  const json = await failed.json();
  assert.equal(json.response_type, "ephemeral");
  assert.match(json.text, /HTTP 404$/);
});

test("GitHub error message is included without markup", async () => {
  globalThis.fetch = async () => new Response(
    JSON.stringify({ message: 'Unexpected inputs provided: ["<!channel>"]' }), { status: 422 },
  );
  const response = await worker.fetch(await slackRequest({ command: "/posting" }), ENV);
  const { text } = await response.json();
  assert.match(text, /HTTP 422 — Unexpected inputs provided: \[channel\]/);
});

test("GET health check", async () => {
  const response = await worker.fetch(new Request("https://relay.example/"), ENV);
  assert.equal(await response.text(), "ok");
});
