# v0.1.0-rc1 Release Readiness Report

## 1. 结论

**NO-GO**

真实 Redis/API/Runner/Web/Docker 能够生成和下载教学、Lorenz、Fourier 与 CSV 视频，但所有真实视频的 QualityReport 都未通过。请求目标为 30 秒时，实际只有 4.2–12 秒，且伴随公式、时间线或画面边界诊断。按 OpenSpec 的 P0 标准，成功渲染不等于可发布。

候选分支为 `release/rc1-readiness`。报告文档内无法自引其所在 Git object SHA；最终证据 SHA 以本报告提交后执行的 `git rev-parse HEAD` 和交付报告为准。代码修复基线为 `a613898`。

## 2. 修改文件

- `reference_scenes/geometry/triangle_congruence.py`：仅修复 import 排序。
- `apps/web/src/app/layout.tsx`、`apps/web/src/app/styles.css`：移除 `next/font/google` 构建期联网，改用系统字体栈。
- `tests/web/workbench/test_workbench_boundaries.py`：防止重新引入 Google Fonts 或缺失字体变量。
- `package-lock.json`：将 transitive `nanoid` 从 3.3.17 更新到 3.3.18，关闭 High advisory。
- `apps/api/.../agent/intent_resolver.py`：约束 Provider 只输出严格 IntentSpec JSON，修正缺资产停止语义，禁止伪造 CSV center。
- `apps/api/.../agent/scientific_planner.py`：移除 CSV benchmark 专属默认参数。
- `apps/api/.../agent/service.py`：遵循 `MANIM_WORKBENCH_COMPUTE_ROOT`，隔离运行时计算缓存。
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
- 核心未解根因是“目标时长未贯穿生成与编译时间线”。Agent 的 30 秒 ContentPlan 与编译 IR 的 10–12 秒时间线分离；教学 Provider 也只产生约 4.8 秒源码。现有 QualityReport 正确拒绝这些产物，但发布链没有在质量失败后执行有界修复或阻止交付。

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

早期全量套件与部分长耗时真实渲染是修复前 checkpoint。由于已经有决定性 QualityReport 失败，不将不同 checkpoint 拼接成 GO 证据；最终提交上的静态、构建和全量 pytest 复测将单独记录。

## 5. 未解决风险

1. 所有真实视频 QualityReport 失败；目标时长、IR/compiler 时间线和发布质量闭环未对齐。
2. 浏览器 console 有未定位 URL 的 404，尚未证明是无害的质量报告轮询。
3. 本地 auth-disabled 模式无法提供两个真实浏览器用户；多用户 owner/Artifact 隔离本轮只有自动化证据。
4. API 停机跨过 sandbox 完成点时会在 lease 恢复后重试；终态与产物唯一，但计算成本可翻倍。
5. 真实 Provider 初始出现过 JSON 合法性和业务语义错误；当前修复需在下一候选提交上重跑全部长耗时视频门禁。

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

1. 将 `target_duration_seconds` 从 ContentPlan/Agent request 贯穿到 AnimationIR timeline 和教学源码，不再使用与请求分离的 10–12 秒硬编码窗口。
2. 将 QualityReport 的有界修复/拒绝发布策略接入真实完成链，分开教学公式诊断与科研 IR 诊断。
3. 为上述两点增加聚焦回归，重跑教学/Lorenz/Fourier/CSV 的真实 Preview/Final 和 QualityReport。
4. 记录并修复浏览器 404 URL，在 auth-enabled 隔离环境执行双用户 Cookie/CSRF/owner/Artifact 验收。
5. 在单一新提交上重跑所有 P0 门禁；只有全绿才能改为 GO 并由用户决定是否创建 `v0.1.0-rc1`。
