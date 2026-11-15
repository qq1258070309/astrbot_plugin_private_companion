# Fork 同步与发布说明

本仓库是 [`menglimi/astrbot_plugin_private_companion`](https://github.com/menglimi/astrbot_plugin_private_companion)
的定制发行分支：保留本地生产环境的功能定制，同时持续跟随上游发版。
上游每发一个 release，自动完成「三方合并 → 机械门禁 → AI 兼容性审查 → 打 tag / Release」。
**发布只到 GitHub，不会自动改动任何运行中的 AstrBot 实例。**

## 1. 分支与版本

| 项 | 规则 |
| --- | --- |
| `main` | 默认分支 = 上游 + 本地定制。AstrBot 读它的 `metadata.yaml` 检查更新 |
| `sync/<tag>` | 临时同步分支，仅在需要人工审查时创建，对应一个待审 PR |
| `UPSTREAM_BASE` | 当前对齐的上游 tag，例如 `v7.1.20` |
| 版本号 | `<上游版本><单个小写字母>`，例如 `7.1.20a`；tag 为 `v7.1.20a` |
| 修订号 | 同一上游基线再次发版时 `a → b → c`；上游发新版时回到 `a`（`7.1.21a`） |

> 为什么不用 `7.1.20.1`：上游 `tools/build_v2_release.py::release_version_key()` 只接受
> `X.Y.Z` 或 `X.Y.Z<单个字母>`，且把版本号硬编码在 5 个文件里并校验一致。
> 字母后缀是上游自身支持的 hotfix 语义，正好表达「基于 7.1.20 的定制修订版」。

版本字段由 `tools/fork_release.py prepare` 一次性重写，因此**每次上游同步都不会产生版本号合并冲突**。

## 2. AstrBot 如何检查更新

AstrBot（含插件更新管理器的自定义源）读取**默认分支** `metadata.yaml` 的 `name` / `version`
与本地已装版本比较，并下载仓库归档。本仓库已把 `metadata.yaml` 的 `repo` 指向自身，
满足「metadata 中的 repo 必须与绑定仓库一致」的校验。

- 在 Dashboard 用仓库地址安装/重装：`https://github.com/qq1258070309/astrbot_plugin_private_companion`
- 之后每次本仓库发布新版本，AstrBot 检查更新即可看到，由你决定何时升级
- Release 里的 zip 与 `SHA256SUMS.txt` 供手动安装与校验，不是更新检测的前提

## 3. 流水线

`.github/workflows/sync-release.yml`，每 6 小时、手动或 `repository_dispatch` 触发：

1. 通过 GitHub API 取上游最新 release tag，与 `UPSTREAM_BASE` 比较；无新版本则结束；
2. `git merge --no-ff <tag>` 做三方合并；
3. `fork_release.py resolve-merge` 确定性解决冲突：版本 / 生成物 / CHANGELOG 类文件取上游后重写；
   其余冲突保留我方版本并记入 `CONFLICTS.json`；
4. `fork_release.py prepare` 重写版本、repo、CHANGELOG、native baseline，并幂等重放页面加载顺序；
5. `tools/fork_gates.sh`：上游全部契约测试 + 页面一致性 + 隐私检查 + 语法编译 +
   本地定制测试 + 发布包构建与 `verify_v2_release.py` 校验；
6. `tools/ai_compat_review.py` 调用 OpenAI 兼容接口审查差异、冲突、门禁结果与定制清单，
   产出 `COMPAT_REPORT.md` 与 `compatible` 判定；
7. **只有**「无需人工裁决 + 机械门禁全过 + AI 判定通过 + 非 dry-run」才提交 `main`、
   打 tag、创建 Release（zip + SHA256SUMS + 兼容性报告）；
8. 任一环节不通过 → 推 `sync/<tag>` 分支并开 PR，附冲突报告 / 门禁日志 / 兼容性报告，**不发 Release**。

### 安全默认

- 未配置 `LLM_API_KEY` 时 AI 审查跳过且判定为不可发布，流程转为 PR，**不会静默自动发版**；
- 任何定制锚点丢失、版本不一致、native baseline 过期都会让 `fork_release.py check` 失败；
- 生成页面产物一律由 `sync_framework_page.py` 重新生成；
- `concurrency` 保证同一时刻只有一个同步任务，避免并发推 main。

## 4. 首次启用清单

1. 打开仓库 **Settings → Actions → General**：
   - 确认 Actions 已启用（fork 仓库首次可能需手动点一次）；
   - **Workflow permissions** 设为 **Read and write permissions**（默认只读会导致无法推 tag / 建 Release）。
2. 打开 **Settings → Secrets and variables → Actions → New repository secret**：
   - `LLM_API_KEY`（必填，用于 AI 兼容性审查）；
   - `LLM_BASE_URL`（可选，默认 `https://api.openai.com/v1`，可填任意 OpenAI 兼容端点）；
   - `LLM_MODEL`（可选，默认 `gpt-4o-mini`）。
3. 在 **Actions → Sync upstream, verify compatibility, and release → Run workflow** 手动跑一次验证，
   可勾选 `dry_run` 只跑检查不发布。
4. 推送 `main` 后，在 **Actions → Publish current main (first release / manual republish)
   → Run workflow** 手动跑一次，产出首个 Release `v7.1.20a`。首个版本由本地三方合并而来，
   没有新的上游 tag 可触发同步流程，因此用这个辅助 workflow 走**同样的门禁 + AI 审查**后发布；
   它不合并、不 bump 版本、不改动 `main`。
5. 之后上游每次发版由 `sync-release.yml` 全自动发布，无需再手动介入。
6. 确认 `main` 的 `metadata.yaml` 版本号与 `UPSTREAM_BASE` 正确后，即可交给定时任务。

> fork 仓库的 `schedule` 在仓库连续 60 天无活动后会被 GitHub 自动停用；
> 届时手动跑一次 workflow 即可恢复。凭据只放 Secrets，**不要写进任何文件、脚本或对话**。

## 5. 待审 PR 怎么处理

PR 标题为「同步上游 `<tag>`（待审，未发布）」，正文含：

- `CONFLICTS.json`：哪些文件用了我方版本、需要人工裁决；
- 机械门禁日志尾部；
- AI 兼容性报告结论。

处理方式：在本地 clone 该 `sync/<tag>` 分支 → 裁决冲突 → 推送 → 重跑 workflow；
或修正 Secrets / 门禁问题后直接重跑。确认无误后删除该临时分支与 PR。

## 6. 回滚

- **回滚到上一版**：`git revert` 发布 commit 或把 `main` 重置到上一个 tag 后强推
  （会改写历史，仅在确认无人依赖时做）；已发布的 Release 可在 GitHub 手动删除；
- **AstrBot 侧**：用上一个版本的 Release zip 重新安装即可；
- 生产服务器永远由你手动决定升级，本仓库不做任何自动部署。

## 7. 本地 dry-run

```bash
# 在干净 clone 中（Python 3.11+ / Node 22+）
python -m pip install PyYAML regex Pillow httpx aiohttp 'cryptography>=42' tzdata
python -X utf8 tools/fork_release.py check
bash tools/fork_gates.sh /tmp/fork-release /tmp/fork-verify
```

排查过程中曾在 Windows 上遇到 `PermissionError: [WinError 32]`（临时 SQLite 文件清理），
纯上游树不受影响；在移除下面这个挂起的过期测试并串行跑完整门禁后未再复现。
`tools/fork_gates.sh` 仍保留 Windows 下对 screen 组的容错兜底（仅降级为 warning），
Linux CI 保持「失败即停」，不放宽任何门禁。

另有一处**已知待迁移项**：`tests/test_lane_capacity_guard.py` 断言的是 7.1.5 内部契约
（`ExactTaskRunner` 无 `waiting` 机制、旧版 `validate_judge` 草稿结构），上游 7.1.20 已重写
这两处，因此该测试在合并树上会报错/挂起。文件保留在仓库但不纳入发布门禁，
详见 [`FORK_CUSTOMIZATIONS.md`](FORK_CUSTOMIZATIONS.md)。这是**测试过期而非生产回归**：
合并树的 `validate_judge` 与上游逐字相同，`claim()` 的容量保护仍在，上游契约测试全通过。

## 8. 红线

- 不把工作区根仓库（含明文凭据与生产 DB）推到任何远端；
- 不在仓库、脚本、报告中写入任何 token / 密码；
- 不自动推送生产服务器、不自动 reload 插件；
- 生成物不手工合并，永远重新生成。

定制明细见 [`FORK_CUSTOMIZATIONS.md`](FORK_CUSTOMIZATIONS.md)。
