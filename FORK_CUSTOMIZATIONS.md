# 本地定制清单

本仓库 = `menglimi/astrbot_plugin_private_companion` 上游版本 + 下列本地定制。
定制以独立 commit 存在于 `main` 历史中；每次上游发版时由 `sync-release` 做三方合并，
而不是重新打补丁。

`tools/fork_release.py check` 会验证下表中的**锚点**是否仍然存在；任一锚点丢失，
自动发布即被阻断并转为人工审查 PR。本文件同时作为 AI 兼容性审查的输入。

## 一、功能定制

| 定制 | 文件 | 关键锚点 | 与上游 v7.1.20 的关系 |
| --- | --- | --- | --- |
| QQ 空间凭据后台保活：按 1 分钟 → 24 小时阶梯自动重取，跨档位私聊管理员，恢复时补一句 | `astrbot_host/qzone_credential_watch.py`、`companion_v2/qzone/credential.py`、`companion_v2/qzone/configuration.py`、`pages/陪伴小屋/config-editor.js` | `credential_admin_notice`、`QzoneCredentialWatch`、`passive_retry_delay_seconds` | 上游无此功能；与上游新增的「生活说说」配置项并存 |
| QQ 表情预回应：命中回复才贴、内部异常隔离、收尾撤销 | `astrbot_host/qq_pre_reply_reaction.py`、`main.py` | `apply_pre_reply_reaction` | 上游无此功能；与上游新增的时段 provider 路由并存于同一钩子 |
| 配置 IMMEDIATE 组状态修复：无 consumer 时不再永久显示「未启动」 | `companion_v2/configuration/service.py` | `ApplyMode.IMMEDIATE` | 上游把 `runtime.read_one` 重构为 `store.read_one`，已采用上游实现并保留该 early return |
| 日程 `presence` 公开短状态字段 | `companion_v2/agenda/planning_output.py` | `"presence"`、`"routine"` | 上游新增 `routine=reading/writing`；两者已合并进提示词与字段白名单 |
| SQLite WAL 连接级大小上限，避免 WAL 只增不减 | `companion_v2/storage/runtime.py` | `WAL_SIZE_LIMIT_BYTES`、`journal_size_limit` | 上游已独立实现等价的 64 MiB 页缓存 + mmap，采用上游实现；仅保留 WAL 限额 |
| 模型路由 fallback、provider 目录扩展 | `astrbot_host/multi_session.py`、`companion_v2/adapters/astrbot/provider_catalog.py` 等 | `routed_fallback` | 上游未覆盖，保留本地实现 |
| 决策页加载顺序修复：`decision-page.js` 必须先于 `app.js` | `pages/陪伴小屋/index.html` | `decision-page.js`、`app.js` 顺序 | 上游会持续改脚本版本号；每次同步由 `fork_release.py reapply-page-order` 幂等重放 |
| 本地回归测试与调试工具 | `tests/test_qq_pre_reply_reaction.py`、`test_qzone_credential_watch.py`、`test_proactive_zone.py`、`test_workbench_status_push.cjs`、`test_host_api_timeout_budget.cjs`、`tools/run_page_check.cjs` | 文件存在 | 已并入 `tools/fork_gates.sh` 门禁 |

### 待迁移：`tests/test_lane_capacity_guard.py`

该文件是 7.1.5 时期新增的回归测试，断言的是**当时的内部契约**：
`ExactTaskRunner` 没有 `waiting` 声明机制、`validate_judge` 的草稿只含
`decision / judge.task_id / judge.state`。上游 7.1.20 重写了这两处
（`validate_judge` 现在还要求 `model_call_id`、`attempt_id`、`signature` 与 operation receipt；
`ExactTaskRunner.run()` 会 `await self.waiting.claim(...)`），因此该文件在合并树上
4 个用例报错、1 个用例挂起。**这是测试过期，不是定制功能丢失**：合并树的
`validate_judge` 与上游逐字相同，`claim()` 仍带 `held >= capacity` 保护，上游全部契约测试通过。
文件保留在仓库中等待按新契约迁移，暂不纳入发布门禁。

## 二、发布契约定制

上游把版本号硬编码在 5 处，并在 `verify_v2_release.py` 里硬校验 `metadata.yaml` 的
`repo` 必须指向上游。为让 AstrBot 从本仓库检查更新，本仓库做了如下确定性改写，
统一由 `tools/fork_release.py prepare` 幂等执行：

- `metadata.yaml` → `version: <上游版本>`（**不带字母后缀**：AstrBot 的 `VersionComparator` 无法解析尾部字母，会退化成 `0.0.0` 导致更新检测失效；fork 修订号放在 Git tag `v<版本>-fork.N` 里）、`repo: https://github.com/qq1258070309/astrbot_plugin_private_companion`
- `pyproject.toml`、`companion_v2/product/__init__.py`、`tools/build_v2_release.py` → 同步版本号
- `tools/verify_v2_release.py` → 期望的 repo 改为本仓库
- `tools/native_capability_baseline.json` → 每次发版刷新 native hashes
- `README.md` → 源代码链接指向本仓库，保留上游署名与链接
- `CHANGELOG.md` → 追加本仓库发版条目
- `UPSTREAM_BASE` → 记录当前对齐的上游 tag

## 三、已被上游吸收、不再单独保留的本地改动

- SQLite 页缓存 / mmap 调优（上游 7.1.20 已实现，参数等价）
- 生活说说发布配置（上游新增，与本仓库的凭据通知配置并存）
- 页面构建产物 `page-build.json`、`workspace-bundles/*.js`（一律取上游并由
  `tools/sync_framework_page.py` 重新生成，绝不手工合并）

## 四、合并裁决原则

1. 上游新增功能与本地定制不冲突时，两边都保留；
2. 上游重写了本地等价实现时，采用上游实现，只保留本地独有的增量；
3. 生成产物一律取上游后重新生成；
4. 版本 / 仓库地址 / CHANGELOG / baseline 类文件取上游，再由 `prepare` 重写定制字段；
5. 其余冲突一律转人工审查 PR，**绝不静默丢弃任何一侧**。
