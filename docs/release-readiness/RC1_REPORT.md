# v0.1.0-rc1 Release Readiness Report

## 1. 结论

**NO-GO（视频时长与发布质量闭环已关闭；RC1 总门禁尚未全部复测）**

本轮已关闭此前的两个决定性代码阻塞：30 秒目标现在贯穿科研 Intent/IR/compiler 与教学源码生成门禁；Runner 完成请求会先生成 QualityReport，`failed` 或缺失报告会把 Job 标记为失败且不注册 Artifact。真实 Docker 复测中，held-out Lorenz 与新 CSV 的 Preview/Final 均为 30.0 秒（CSV 首次 Preview 为 30.07 秒），没有 error 级质量诊断。

当前仍不把整体 RC1 改为 GO：本轮环境没有 `DEEPSEEK_API_KEY`，因此不能在最终修复提交上重跑真实教学 Provider；浏览器 404、双用户 owner 隔离和全部 RC1 门禁也仍需在同一最终 commit 上复测。可以合并本次最小修复，但不得据此创建 RC1 tag。

候选分支为 `release/rc1-readiness`。报告文档内无法自引其所在 Git object SHA；最终证据 SHA 以本报告提交后执行的 `git rev-parse HEAD` 和交付报告为准。代码修复基线为 `a613898`。

## 2. 修改文件

- `reference_scenes/geometry/triangle_congruence.py`：仅修复 import 排序。
- `apps/web/src/app/layout.tsx`、`apps/web/src/app/styles.css`：移除 `next/font/google` 构建期联网，改用系统字体栈。
- `tests/web/workbench/test_workbench_boundaries.py`：防止重新引入 Google Fonts 或缺失字体变量。
- `package-lock.json`：将 transitive `nanoid` 从 3.3.17 更新到 3.3.18，关闭 High advisory。
- `apps/api/.../agent/intent_resolver.py`：约束 Provider 只输出严格 IntentSpec JSON，修正缺资产停止语义，禁止伪造 CSV center。
- `apps/api/.../agent/scientific_planner.py`：移除 CSV benchmark 专属默认参数。
- `apps/api/.../agent/service.py`、`agent/orchestrator.py`：遵循计算缓存目录并把请求目标时长注入 Intent。
- `apps/api/.../agent/visual_director.py`、`compiler/manim.py`：按目标时长确定性重排 IR；将长动画拆成不超过 3 秒的活跃段；用低内存连续路径实现 CSV 渐进折线，并收紧 Lorenz 画面尺度。
- `apps/api/.../code_generation/service.py`：在教学源码保存和渲染前执行 ContentPlan 时间线门禁，失败进入既有最多两次的有界修复。
- `apps/api/.../quality/completion.py`、`quality/orchestration.py`、`jobs/router.py`：区分教学公式与科研 IR 诊断；完成前持久化质量报告；失败或缺证据时拒绝 Artifact 发布。
- `apps/runner/.../phase5_runtime.py`、`queue/*`：将 API 的质量拒绝终态反馈给 Runner，避免将其误报为成功。
- `apps/api/.../tools/kernels.py`：支持 `timestamp`，从真实数据确定异常中心和自适应窗口。
- `tests/agent/test_intent.py`、`tests/agent/test_asset_version.py`：覆盖上述 schema、停止、provenance、参数与缓存边界。
- `docs/release-readiness/RC1_EXECUTION_LOG.md`、本报告：记录脱敏命令、修复前后证据和 NO-GO 根因。

## 3. 问题与根因

### pytest “卡住”

完整套件没有死锁。约 83 秒的无输出窗口来自 `test_p0_gold_meets_first_render_and_science_rates` 顺序执行真实 Docker preview。faulthandler 栈始终位于有 60 秒 deadline 的 sandbox 子进程轮询；测试自行完成并正常退出。未删除、skip、xfail 或放宽断言。

### 字体构建失败

`layout.tsx` 的五组 `next/font/google` 会在 production build 期间访问 Google Fonts。已改为系统字体栈；死代理环境中清理 `.next` 后构建仍成功。

### 真实运行链路

- Provider 最初输出过错误 schema/version/tool shape，且会对 CSV 伪造 center；已收紧格式与服务端后校验。
- CSV planner 将历史 benchmark 的 `350/20` 注入新数据，并因 API 忽略缓存目录环境变量而命中旧 NPZ；两者均已修复。
- 原目标时长未贯穿生成与编译时间线：Agent service 没有把请求时长传入 orchestrator，Visual Director 使用固定 4–12 秒模板；教学服务只检查安全和可渲染性，没有在保存前检查 ContentPlan 时间线。两处均已修复。
- 原发布顺序先把 Job/Artifact 标记成功，再尝试写 QualityReport，导致失败质量仍可下载。现改为先生成报告，缺失或 `failed` 时 Job 进入失败且不注册 Artifact；科研 `compiled_ir` 不再误用教学公式完整性诊断。
- CSV 首轮 Final 在 1080p60 下返回 247/SIGKILL：长达 12.9 秒的单个活跃动画在 2 GiB sandbox 内累积过多 Cairo 帧内存。改为最长 3 秒的确定性片段，并将逐帧多 `Line` 的折线改为单 `VMobject` 连续路径后，Final 在 23.08 秒内成功。

## 4. 验证证据

| 门禁 | 命令/方式 | 结果 | 证据 |
| --- | --- | --- | --- |
| OpenSpec | `openspec validate prepare-rc1-release-readiness` | pass | CLI output |
| Ruff/diff | `uv run ruff check .`; `git diff --check` | pass | execution log |
| Web | lint, typecheck, dead-proxy production build | pass | execution log |
| production audit | `npm audit --omit=dev --audit-level=high` | pass, 0 vulnerabilities | lockfile + log |
| pytest checkpoint | full suite twice | 582 passed / 133.18s; 582 passed / 128.97s | `/tmp/manim-pytest-full-run-{1,2}.log` |
| contracts | `generate_contracts.py --check` | pass, schema 1.10 | execution log |
| migration | empty DB upgrade; 0008→0007→0008 | pass, head 0008 | `/tmp/manim-rc1-alembic-empty-upgrade.log` |
| teaching Docker | Preview + Final + MP4 decode/download | render pass; quality 0/100 fail | `teaching.json` |
| research Docker | Lorenz Preview + Final + critic/provenance | render pass; quality 0/100 fail | `research.json` |
| CSV Docker | AssetVersion + Preview + Final | data/provenance pass; quality 17/100 fail | `csv.json` |
| safety stop | missing CSV + unknown paper | pass; no tool/code/job | `safety.json` |
| browser | production Chromium Preview/Final/download/refresh | flow pass; quality fail; 404 risk | `browser.json`, PNG |
| recovery | restart API during Final | unique success, 4 artifacts, attempt_count=2 | `recovery.json` |
| DeepSeek held-out | ≥8 requests across 4 categories | routing improved; business/quality gate fail | evidence JSON + SQLite metadata |
| targeted regression | Agent/Phase5/Phase7/Phase9 | 358 passed | pytest output |
| duration Docker closure | held-out Lorenz + new CSV, Preview/Final | 4/4 passed; 30.0s; no error diagnostics | `/tmp/manim-rc1-duration-quality/report.json` |
| CSV Final resource regression | 1080p60 real sandbox | passed in 23.08s after 3s chunking | `/tmp/manim-rc1-duration-quality/debug-csv-final-4/` |
| publication fail-closed | migrated DB API integration | failed report => failed Job, zero Artifact rows | Phase 9 integration test |
| final pytest candidate | full suite twice | 594 passed / 76.37s; 594 passed / 76.75s | `/tmp/manim-pytest-duration-quality-pass-{1,2}.log` |
| final static/contracts | Ruff; contract check; diff check | pass | command output |
| final Web | lint; typecheck; production build | pass | command output |

早期全量套件与部分长耗时真实渲染是修复前 checkpoint。由于已经有决定性 QualityReport 失败，不将不同 checkpoint 拼接成 GO 证据；最终提交上的静态、构建和全量 pytest 复测将单独记录。

## 5. 未解决风险

1. 最终修复提交尚未重跑真实 DeepSeek 教学与科研 held-out；当前 shell 没有 Provider key。
2. 浏览器 console 有未定位 URL 的 404，尚未证明是无害的质量报告轮询。
3. 本地 auth-disabled 模式无法提供两个真实浏览器用户；多用户 owner/Artifact 隔离本轮只有自动化证据。
4. API 停机跨过 sandbox 完成点时会在 lease 恢复后重试；终态与产物唯一，但计算成本可翻倍。
5. 质量报告写入与 Job 终态转换是顺序事务；取消/完成极端竞态已保持 fail-closed，但后续仍可收敛为单事务状态转换。

## 6. Git 状态与提交

- 分支：`release/rc1-readiness`
- 起始 SHA：`64c0f0608327fe1a4d8ed37f01fb45b7e56628ec`
- 代码修复基线：`a613898`
- 提交：`c7502bf`、`5f3915f`、`3999199`、`a613898`，以及本报告的 docs commit
- 推送：否
- tag：未创建
- 外部小范围试用阶段：已按用户指示取消，不再列为后续任务
- 最终 HEAD 与 clean 状态以交付时 `git rev-parse HEAD` / `git status --short` 为准

## 7. 最小阻塞项关闭顺序

1. 在有 DeepSeek key 的环境重跑教学、科研和资产 held-out，确认 Provider 生成也满足新时间线门禁。
2. 记录并修复浏览器 404 URL，在 auth-enabled 隔离环境执行双用户 Cookie/CSRF/owner/Artifact 验收。
3. 在单一候选提交上重跑 Web、迁移、契约、全量 pytest 两次和全部真实 P0 门禁。
4. 只有全部门禁全绿才能改为 GO，并由用户决定是否创建 `v0.1.0-rc1`。
