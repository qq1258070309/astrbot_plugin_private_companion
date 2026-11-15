"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

/* The account workspace asks for a 60 s budget when saving the shared model.
   embedded-bridge.js only honours it when api() forwards options; otherwise the
   bridge keeps its 18 s default and rejects a save that already reached disk. */
const source = fs.readFileSync(path.join(__dirname, "../pages/\u5bbf\u4e3b\u7ba1\u7406/app.js"), "utf8");
const apiSource = source.slice(source.indexOf("  async function api("), source.indexOf("  function setBusy("));
const bridgeSource = fs.readFileSync(path.join(__dirname, "../pages/\u966a\u4f34\u5c0f\u5c4b/embedded-bridge.js"), "utf8");

function harness() {
  const calls = {get: [], post: []};
  const bridge = {
    apiGet: async (...args) => { calls.get.push(args); return {status: "ok", data: {ok: "get"}}; },
    apiPost: async (...args) => { calls.post.push(args); return {status: "ok", data: {ok: "post"}}; },
  };
  const context = vm.createContext({
    bridge,
    unwrap: value => value?.data,
    window: {setTimeout: () => 0, clearTimeout: () => {}},
  });
  vm.runInContext(`${apiSource}\nglobalThis.api = api;`, context);
  return {api: context.api, calls};
}

test("the shared model save budget reaches the embedded workspace bridge", async () => {
  const h = harness();
  const result = await h.api("POST", "accounts/model-provider", {provider_id: "p1"}, 60000);
  assert.deepEqual(result, {ok: "post"});
  assert.equal(h.calls.post.length, 1);
  assert.equal(h.calls.post[0][0], "accounts/model-provider");
  assert.deepEqual(h.calls.post[0][1], {provider_id: "p1"});
  assert.equal(h.calls.post[0][2].timeoutMs, 60000);
  assert.deepEqual(Object.keys(h.calls.post[0][2]), ["timeoutMs"]);
});

test("status reads and the default budget are forwarded too", async () => {
  const h = harness();
  await h.api("GET", "host/status", {}, 30000);
  await h.api("GET", "accounts");
  assert.equal(h.calls.get[0][2].timeoutMs, 30000);
  assert.equal(h.calls.get[1][2].timeoutMs, 30000);
  assert.deepEqual(Object.keys(h.calls.get[0][1]), []);
});

test("end to end: the save makes the real bridge wait 60 s instead of 18 s", async () => {
  const messages = [], timers = [];
  let onMessage;
  const parent = {postMessage(message) { messages.push(message); }};
  const window = {
    parent,
    addEventListener(type, handler) { if (type === "message") onMessage = handler; },
    setTimeout(callback, ms) { const timer = {callback, ms, cleared: false}; timers.push(timer); return timer; },
    clearTimeout(timer) { if (timer) timer.cleared = true; },
  };
  const document = {addEventListener() {}, querySelectorAll: () => [], documentElement: {dataset: {}}};
  const context = vm.createContext({window, document, parent,
    setTimeout: window.setTimeout, clearTimeout: window.clearTimeout,
    CustomEvent: class { constructor(type, init = {}) { this.type = type; this.detail = init.detail; } }});
  vm.runInContext(bridgeSource, context);
  vm.runInContext(`const bridge = window.AstrBotPluginPage;
    const unwrap = value => value?.data;
    ${apiSource}
    globalThis.save = () => api("POST", "accounts/model-provider", {provider_id: "p1"}, 60000);`, context);

  const pending = context.save();
  const request = messages.find(message => message.kind === "request");
  assert.equal(request.method, "POST");
  assert.equal(request.path, "accounts/model-provider");
  assert.equal(request.timeoutMs, 60000, "the parent page receives the 60 s budget too");
  assert.ok(timers.some(timer => timer.ms === 61000), "bridge keeps a 61 s guard, not the 18 s default");
  assert.ok(!timers.some(timer => timer.ms === 19000), "the short default timer is gone");

  onMessage({source: parent, data: {channel: "companion-workspace", kind: "response",
    requestId: request.requestId, ok: true, data: {status: "ok", data: {saved: true}}}});
  assert.deepEqual(JSON.parse(JSON.stringify(await pending)), {saved: true});
});
