/* Performance mode keeps the heavy cottage assets inert until checked. */
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const PAGE = path.join(__dirname, "..", "pages", "陪伴小屋");
const INDEX = fs.readFileSync(path.join(PAGE, "index.html"), "utf8");
const GATE = fs.readFileSync(path.join(PAGE, "performance-gate.js"), "utf8");
const SCHEMA = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "_conf_schema.json"), "utf8"));

test("官方配置页第一组就是性能模式开关", () => {
  assert.equal(Object.keys(SCHEMA)[0], "performance");
  assert.equal(SCHEMA.performance.items.enabled.type, "bool");
  assert.equal(SCHEMA.performance.items.enabled.default, false);
});

test("完整小屋资源位于惰性 template，首屏不直接下载", () => {
  const start = INDEX.indexOf('<template id="companion-full-assets">');
  const end = INDEX.indexOf("</template>", start);
  assert.ok(start > 0 && end > start, "缺少完整资源 template");
  const inert = INDEX.slice(start, end);
  for (const asset of ["bundle.css", "assets/voxel-room.js", "app.js", "models-page.js"]) {
    assert.match(inert, new RegExp(asset.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
  const before = INDEX.slice(0, start);
  assert.doesNotMatch(before, /<script[^>]+src="app\.js/);
  assert.doesNotMatch(before, /<link[^>]+href="bundle\.css/);
  const cssSources = JSON.parse(fs.readFileSync(path.join(PAGE, "css-sources.json"), "utf8"));
  assert.ok(cssSources.includes("tokens.css"));
  assert.ok(cssSources.includes("models-page.css"));
  assert.match(INDEX, /<script defer src="performance-gate\.js\?v=/);
  assert.match(INDEX, /data-companion-booting/);
});

test("首屏只激活到 app.js，其余模块在 shell 可见后补齐且顺序不变", async () => {
  const appended = [], timers = [], rafs = [];
  const makeNode = (tagName, attrs = {}) => ({
    nodeType: 1, tagName, attrs, listeners: {},
    getAttribute(name) { return Object.hasOwn(attrs, name) ? attrs[name] : null; },
    addEventListener(type, handler) { this.listeners[type] = handler; },
    cloneNode() { return makeNode(tagName, { ...attrs }); },
  });
  const templateNodes = [
    makeNode("LINK", {rel: "stylesheet", href: "bundle.css?v=1"}),
    makeNode("LINK", {rel: "preload", href: "assets/voxel-room.js"}),
    makeNode("SCRIPT", {src: "assets/lucide.min.js"}),
    makeNode("SCRIPT", {src: "app.js?v=1"}),
    makeNode("SCRIPT", {src: "maintenance-page.js?v=1"}),
    makeNode("SCRIPT", {src: "module-ready.js?v=1"}),
  ];
  const root = {dataset: {}, removeAttribute() {}};
  const document = {
    documentElement: root,
    getElementById(id) { return id === "companion-full-assets" ? {content: {childNodes: templateNodes}} : null; },
    head: {appendChild(node) { appended.push(node); return node; }},
    createElement() { return {className: "", appendChild() {}, addEventListener() {}}; },
    body: {replaceChildren() {}},
    title: "",
  };
  const window = {
    AstrBotPluginPage: {
      ready: () => Promise.resolve(),
      apiGet: () => Promise.resolve({status: "ok", data: {enabled: false}}),
    },
  };
  const context = vm.createContext({
    window, document,
    requestAnimationFrame(callback) { rafs.push(callback); return rafs.length; },
    setTimeout(callback, ms) { const timer = {callback, ms}; timers.push(timer); return timer; },
    clearTimeout() {},
  });
  vm.runInContext(GATE, context);
  /* The gate resolves its bridge promises inside the vm realm; one host macrotask
     drains that whole chain reliably (plain Promise.resolve() ticks do not). */
  await new Promise(resolve => setImmediate(resolve));

  const urls = () => appended.map(node => node.getAttribute("src") || node.getAttribute("href"));
  assert.deepEqual(urls(), ["bundle.css?v=1", "assets/voxel-room.js",
    "assets/lucide.min.js", "app.js?v=1"], "首屏不应请求 app.js 之后的管理模块");
  assert.ok(appended.every(node => node.tagName !== "SCRIPT" || node.async === false));

  appended[0].listeners.load();
  for (let round = 0; round < 3; round += 1) {
    for (let i = 0; i < 12 && rafs.length; i += 1) rafs.shift()();
    for (let i = 0; i < 12 && timers.length; i += 1) timers.shift().callback();
    await Promise.resolve();
  }
  assert.deepEqual(urls(), ["bundle.css?v=1", "assets/voxel-room.js",
    "assets/lucide.min.js", "app.js?v=1", "maintenance-page.js?v=1", "module-ready.js?v=1"]);
  assert.equal(appended.at(-1).getAttribute("src"), "module-ready.js?v=1",
    "模块就绪标记必须仍在最后，才能触发既有的重渲染");
  assert.ok(appended.every(node => node.tagName !== "SCRIPT" || node.async === false));
  assert.equal(root.dataset.companionPerformanceReady, "");
});

test("真实 template 里 app.js 之后的模块确实被移出首屏", () => {
  const start = INDEX.indexOf('<template id="companion-full-assets">');
  const end = INDEX.indexOf("</template>", start);
  const inert = INDEX.slice(start, end);
  const srcs = [...inert.matchAll(/<script[^>]*src="([^"]+)"/g)]
    .map(match => match[1].split("?")[0]);
  const boundary = srcs.findIndex(name => name === "app.js");
  assert.ok(boundary > 0, "app.js 必须是首屏分界");
  assert.equal(srcs.at(-1), "module-ready.js", "模块就绪标记必须排在最后");
  const sizeOf = names => names.reduce((sum, name) => {
    const file = path.join(PAGE, name);
    return sum + (fs.existsSync(file) ? fs.statSync(file).size : 0);
  }, 0);
  const deferredBytes = sizeOf(srcs.slice(boundary + 1));
  assert.ok(deferredBytes > 1_500_000,
    `延后批次应至少 1.5 MB，实际 ${deferredBytes} 字节`);
  assert.ok(deferredBytes < sizeOf(srcs.slice(0, boundary + 1)) + deferredBytes);
});

test("性能门先询问官方设置，关闭时按原顺序激活完整资源", () => {
  assert.match(GATE, /host\/performance/);
  assert.match(GATE, /apiGet\(ENDPOINT/);
  assert.match(GATE, /showLite/);
  assert.match(GATE, /activateFull/);
  assert.match(GATE, /node\.async = false/);
  assert.match(GATE, /removeAttribute\("data-companion-booting"\)/);
  assert.match(GATE, /replaceChildren\(page\)/);
});
