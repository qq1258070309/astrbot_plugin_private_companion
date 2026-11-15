/* notifyStatus 的短路：同一份快照只推一次。
   订阅者（决策页卡片、表达页预览）在自己的 onStatus 回调里会重画、甚至再读一次；
   如果每次 paint 都无条件推，就是「推 → 重画 → 再推」的循环——表达页切换模块时
   曾因此停在上一帧，并把大量重复请求打到桥上。 */
const fs = require("node:fs");
const path = require("node:path");

const source = fs.readFileSync(
  path.join(__dirname, "..", "pages", "陪伴小屋", "workbench-page.js"), "utf8");

const checks = [
  [/function notifyStatus\(\) \{/, "notifyStatus 存在"],
  [/if \(!onStatus\) return;/, "没有订阅者时直接返回"],
  [/const snapshot = state\.status \|\| null;/, "取当前快照"],
  [/if \(snapshot === lastNotified\) return;/, "同一份快照只推一次"],
  [/lastNotified = snapshot;/, "记住已推过的快照"],
  [/let lastNotified = null;/, "短路状态在本实例内"],
  [/function paint\(\) \{\n      const root = mountPoint\(\);\n      notifyStatus\(\);/, "paint 经 notifyStatus 推状态"],
];
const failed = checks.filter(([pattern]) => !pattern.test(source)).map(([, label]) => label);
if (failed.length) {
  console.error("missing:", failed.join(", "));
  process.exit(1);
}
/* 读取与保存成功分支里不能再有第二处直接调用，否则同一份快照会推两遍。 */
const direct = source.match(/if \(onStatus\) onStatus\(/g) || [];
if (direct.length) {
  console.error("direct onStatus calls left:", direct.length);
  process.exit(1);
}
console.log("workbench status push ok");
