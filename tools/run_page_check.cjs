/* 用本机已装的浏览器跑 tools/check_*.cjs 验收脚本。
 *
 * 为什么需要它：check_*.cjs 直接 require("playwright")，而这台机器上既没有
 * playwright 包、也没有下载过它捆绑的 Chromium。装一份完整 playwright 只为跑
 * 页面验收并不划算——本机已有 Edge，playwright-core 能直接驱动它。
 *
 * 用法：
 *   npm i playwright-core   （或在任意目录装一份，再用 PLAYWRIGHT_CORE 指过去）
 *   node tools/run_page_check.cjs tools/check_product_page.cjs <outputDir>
 *
 * 环境变量：
 *   PLAYWRIGHT_CORE  playwright-core 的目录（默认按 'playwright-core' 解析）
 *   BROWSER_PATH     浏览器可执行文件（默认 Edge 的常见安装路径）
 *   BRIDGE           SDK 的 plugin_page_bridge.js（默认取本机 astrbot 安装目录）
 *
 * 说明：脚本本身只改两件事——把 require("playwright") 接到 playwright-core，
 * 并把浏览器换成 Edge；验收断言与页面行为都不在这里动。
 */
const fs = require("node:fs");
const path = require("node:path");
const Module = require("node:module");

const CORE = process.env.PLAYWRIGHT_CORE || "playwright-core";
const corePath = require.resolve(CORE, {paths: [process.cwd(), __dirname]});
const core = require(corePath);

const CANDIDATES = [
  process.env.BROWSER_PATH,
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
].filter(Boolean);
const executablePath = CANDIDATES.find(candidate => fs.existsSync(candidate));
if (!executablePath) {
  console.error("找不到可用浏览器，请设置 BROWSER_PATH。");
  process.exit(2);
}

/* check_*.cjs 里的 `require("playwright")` 一律转发到 playwright-core，并换成
   真实存在的浏览器；其余导出保持原样。 */
const originalResolve = Module._resolveFilename;
Module._resolveFilename = function (request, parent, ...rest) {
  if (request === "playwright") return corePath;
  return originalResolve.call(this, request, parent, ...rest);
};
require.cache[corePath] = {
  id: corePath, filename: corePath, loaded: true,
  exports: {chromium: {launch: options => core.chromium.launch({channel: "msedge", executablePath, ...options})}},
};

/* 默认 SDK 桥：本机 uv 安装的 astrbot 自带一份，插件页验收要拿它做对照。 */
const DEFAULT_BRIDGE = path.join(process.env.APPDATA || "",
  "uv", "tools", "astrbot", "Lib", "site-packages", "astrbot", "dashboard", "plugin_page_bridge.js");

const [script, ...rest] = process.argv.slice(2);
if (!script) {
  console.error("usage: node tools/run_page_check.cjs <check script> [outputDir] [额外参数...]");
  process.exit(2);
}
const target = path.resolve(script);
const mod = require(target);
if (typeof mod.run !== "function") {
  console.error("这个脚本没有导出 run()，请直接 node 它。", target);
  process.exit(2);
}
const bridgePath = process.env.BRIDGE || DEFAULT_BRIDGE;
if (!fs.existsSync(bridgePath)) console.error("提示：SDK 桥不存在，", bridgePath);

core.chromium.launch({channel: "msedge", executablePath})
  .then(browser => mod.run({
      browser,
      outputDir: path.resolve(rest[0] || "page-check-output"),
      bridgePath,
      replyOnly: rest.includes("--reply-only"),
      identityOnly: rest.includes("--identity-only"),
    })
    .then(report => {
      console.log(JSON.stringify({passed: report.passed, checks: report.checks,
        browserErrors: report.browserErrors, serverErrors: report.serverErrors, posts: report.posts}, null, 2));
      const dirty = (report.browserErrors || []).length || (report.serverErrors || []).length;
      process.exitCode = dirty ? 1 : 0;
    })
    .finally(() => browser.close()))
  .catch(error => { console.error(error.message); process.exitCode = 1; });
