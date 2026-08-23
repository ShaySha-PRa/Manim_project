# RC1 Release Readiness Execution Log

本文件为追加式执行记录。密钥、完整环境变量、Cookie、Token、密码和敏感资产内容不得写入。

## 2026-08-23T15:25:52+08:00 — 阶段 0：基线与范围冻结

- Commit SHA：`64c0f0608327fe1a4d8ed37f01fb45b7e56628ec`
- 分支：`release/rc1-readiness`
- 来源：`main` 与 `origin/main` 均为 `64c0f06`，ahead/behind 为 `0/0`
- 根仓库状态：存在已识别的 `.gitignore` 本地修改，仅用于忽略 `/openspec/`；未删除或覆盖
- 新 worktree 初始状态：从 `64c0f06` 创建，产品代码无未提交修改；随后复制本地 OpenSpec 并加入本地规划忽略规则
- OpenSpec：`prepare-rc1-release-readiness` proposal/design/tasks/spec 已完整阅读

### Gate 0-A：远端与 Git 基线

- 命令：`git fetch origin`
- 退出码：`0`
- 命令：`git pull --ff-only`
- 退出码：`0`
- 结果：`Already up to date.`；`main == origin/main == 64c0f06`
- 证据：本日志与 Git refs

### Gate 0-B：OpenSpec 严格校验

- 命令：`openspec validate prepare-rc1-release-readiness --strict --json --no-interactive`
- 退出码：`0`
- 结果：change valid，无 issues；OpenSpec root healthy
- 证据：`openspec/changes/prepare-rc1-release-readiness/`

### Gate 0-C：执行环境快照

- Python launcher：`Python 3.14.6`；项目后续命令以 `uv` 锁定环境为准
- Node：`v22.23.1`
- npm：`10.9.8`
- uv：`0.12.0`
- Docker CLI：`29.1.3`
- `uv.lock` SHA-256：`b06b5bf8282180ab0e384f65c7da9f9c448e4fff11686559df148506bfd70d17`
- `package-lock.json` SHA-256：`51a28200f7c08dc756f29085ccefe188682d2b0ef9f6bebb597a55ceb8f9a1a2`

### Commit 规划

1. `fix: satisfy geometry reference scene lint`
2. `fix: remove web build-time font network dependency`
3. `test: prevent release suite from hanging`（仅在确认并修复根因后）
4. 真实验收脚本/证据（如确有必要）
5. `docs: add rc1 release-readiness evidence`

未授权操作：不推送分支、不创建 PR、不创建或推送 `v0.1.0-rc1` tag。

## 2026-08-23 — 阶段 1A：仓库卫生与 Ruff

### 环境纠正

- 首次命令：`uv run ruff check reference_scenes/geometry/triangle_congruence.py`
- 退出码：`1`（环境建立失败，尚未执行 Ruff）
- 原因：`uv` 默认选择 Python 3.14.6，SciPy 1.15.3 无匹配 wheel，源码构建又缺少 Fortran compiler
- 修复：`uv sync --frozen --python 3.10`
- 复测：使用 Python 3.10.20 成功安装锁定的 50 个包，未修改 `uv.lock`

### Gate 1-A：目标 Ruff 修复

- 复现命令：`uv run ruff check reference_scenes/geometry/triangle_congruence.py`
- 复现退出码：`1`
- 原因：首行 `from manim import ...` 未满足 Ruff I001 import 排序
- 修复：仅对目标文件执行 Ruff import 排序，无行为变化
- 复测命令：目标 Ruff、`uv run ruff check .`、契约同步、`git diff --check`
- 复测退出码：均为 `0`

### Gate 1-B：格式基线

- 目标文件：`ruff format --check` 通过
- 全仓：`ruff format --check .` 退出码 `1`，报告 59 个历史文件待格式化、236 个已格式化
- 处理：按既有策略保留历史基线，不批量格式化无关文件

### Gate 1-C：Web 静态检查

- 首次结果：worktree 尚未安装 Node 依赖，`eslint: not found`，退出码 `127`
- 环境修复：`npm ci --ignore-scripts` 成功，未修改 lockfile
- 复测：`npm --prefix apps/web run lint` 与 `npm --prefix apps/web run typecheck` 均退出码 `0`

### Gate 1-D：M1–M3 清理边界

- 命令：`git worktree prune`、`git worktree list`、精确文本搜索
- 退出码：`0`
- 结果：仅保留 `main` 与 `release/rc1-readiness` worktree；未发现需要删除的 experiment-lab、realtime-lab、M1–M3 或 `/lab` 候选范围引用

### 新发现：production dependency audit blocker

- 命令：`npm audit --omit=dev --audit-level=high`
- 退出码：`1`
- 结果：`next@16.3.0 -> postcss@8.5.23 -> nanoid@3.3.17` 命中 High advisory；安全版本为 `>=3.3.18`
- 状态：待以独立最小 lockfile 修复关闭；不得混入 Ruff commit

### 阶段 1A 提交

- Commit：`c7502bf fix: satisfy geometry reference scene lint`
- 内容：目标 import 排序、OpenSpec 本地忽略规则、RC1 追加式执行日志
- 推送：否

## 2026-08-23 — 阶段 1B：Production dependency audit

- 根因：`postcss@8.5.23` 允许 `nanoid ^3.3.16`，锁文件固定在存在 High advisory 的 `3.3.17`
- 最小修复：仅将 `package-lock.json` 中的 transitive `nanoid` 更新到 `3.3.18`
- `package.json`、Next、PostCSS 和其他依赖版本未改变
- 复测命令：`npm ci --ignore-scripts`、`npm audit --omit=dev --audit-level=high`
- 退出码：均为 `0`
- 结果：实际安装 `nanoid 3.3.18`；production audit 为 `0 vulnerabilities`

## 2026-08-23 — 阶段 2：离线 Web production build

### 根因

- `apps/web/src/app/layout.tsx` 通过 `next/font/google` 声明五组字体
- Next.js production build 会在编译期访问 Google Fonts；受限网络下因此失败

### 修复

- 删除全部 `next/font/google` import 与运行时字体变量注入
- 在全局 CSS 中定义 display/body/script/mono/CJK 系统字体栈
- 未添加字体下载脚本或来源/许可不明确的字体文件
- 新增 Python 防回归测试，禁止 `next/font/google`、Google Fonts URL 和缺失字体变量

### 验证

- 聚焦测试：`tests/web/workbench/test_workbench_boundaries.py`，`5 passed`
- Web lint：退出码 `0`
- Web typecheck：退出码 `0`
- 干净构建前删除：仅 `apps/web/.next` 构建缓存
- 离线等价构建：将 HTTP/HTTPS/ALL proxy 指向不可用的 `127.0.0.1:9` 后执行 production build
- Build：退出码 `0`，6/6 static pages 生成，无外部字体请求
- Production HTTP：`/workbench` 返回 `200`；默认本地模式 `/login` 返回 `307`
- Chromium 桌面 1440x1000 与移动 390x844 截图成功；系统字体下中文、导航、错误状态和按钮可读，无裁切或溢出
- 临时截图：`/tmp/manim-rc1-workbench-desktop.png`、`/tmp/manim-rc1-workbench-mobile.png`
- 已知说明：此阶段未启动 API，因此工作台按预期显示“无法恢复会话”；完整业务页面留待真实运行阶段验证
- Production server 已用 SIGINT 停止；未保留后台 Web 进程

### 阶段 2 提交

- Commit：`3999199 fix: remove web build-time font network dependency`
- 推送：否

## 2026-08-23 — 阶段 3/4：pytest 长耗时诊断与重复性

### 收集与首轮诊断

- 收集命令：`uv run pytest --collect-only -q 2>&1 | tee /tmp/manim-pytest-collect.log`
- 收集结果：退出码 `0`，当前 commit 收集 `582` 项；比任务包的约数多 1 项，来自本次新增的字体网络依赖回归测试
- 诊断命令：`uv run pytest -vv --durations=50 -o faulthandler_timeout=60 2>&1 | tee /tmp/manim-pytest-full.log`
- 首轮结果：退出码 `0`，`582 passed in 133.18s`
- 首轮证据：`/tmp/manim-pytest-full-run-1.log`

### 长时间无输出的根因

- 最后开始但暂未完成的 node id：`tests/agent/test_docker_p0.py::test_p0_gold_meets_first_render_and_science_rates`
- faulthandler 栈：位于 `SandboxExecutor` 的受控 `Popen` 轮询，并由 `_render_preview` 调用；不是 Redis、SQLite、event loop 或无 deadline 的后台循环
- 运行中检查：内存、磁盘充足；没有等待中的 Redis 请求；未发现冲突端口或同名 Manim sandbox 容器
- 该测试顺序执行当前 P0 gold set 的真实 Docker preview 渲染，测试内部不输出逐 case 进度；CI/历史 `pytest -q` 因此会出现约 83 秒静默窗口
- 每个 preview 已由 `PROFILE_CONFIGS` 的 `60s` sandbox deadline 保护；timeout 会映射为明确的 `SANDBOX_TIMEOUT`，已有 unit/failure-path 测试覆盖
- 结论：复现的是“真实渲染长耗时且无中间输出”，不是永久挂起、资源泄漏或退出缺陷；不通过 skip、放宽 timeout、删测试或降低断言处理

### 隔离复测

- 命令：`uv run pytest tests/agent/test_docker_p0.py::test_p0_gold_meets_first_render_and_science_rates -vv -s --setup-show -o faulthandler_timeout=30`
- Docker 不可见的受限 shell 运行：按测试既有条件 skip，仅用于确认环境边界，不作为通过证据
- Docker daemon 可用环境运行：退出码 `0`，`1 passed in 83.83s`
- 30 秒诊断栈仍显示有界 `SandboxExecutor` 子进程轮询；测试随后自行完成
- 证据：`/tmp/manim-pytest-docker-p0-isolated.log`

### 连续两次完整结果

- Run 1：`582 passed in 133.18s`，最慢项 `82.68s`
- Run 2：`582 passed in 128.97s`，同一 commit、Python 3.10.20、同一依赖配置
- Run 2 命令：`uv run pytest -vv --durations=50 2>&1 | tee /tmp/manim-pytest-full-run-2.log`
- Run 2 退出码：`0`
- 两轮均未人工中止，pytest 正常退出
- 两轮结束后检查：无 `manim-wb-*`/Manim workbench 容器残留；无 API/Runner/pytest 后台进程残留
- 未清理或修改系统中与本项目无关的其他容器、Redis 或用户数据
- CI 核心命令为 `uv run pytest -q`，测试范围与本地一致；本地 release 诊断命令增加可见性与慢测试证据，未降低 CI 门禁
- 当前代码无需 pytest 修复提交；根因是对真实 Docker 验收的静默耗时误判，修改执行日志即可准确区分

## 2026-08-23 — 阶段 5：契约、迁移与锁定依赖复现

### 空数据库 migration

- 隔离目录：`/tmp/manim-rc1-migration.lb3Ax1/`，仅包含本次新建的临时 SQLite 数据库
- 命令：以 `MANIM_WORKBENCH_DATABASE_URL=sqlite:////tmp/manim-rc1-migration.lb3Ax1/empty.db` 执行 `uv run alembic upgrade head`
- 退出码：`0`
- 结果：从空库顺序应用 `0001_phase3` 至 `0008_asset_versions`；`alembic current` 为 `0008_asset_versions (head)`
- 结构核验：`asset_versions` 表存在，append-only update/delete 两个 trigger 均存在
- 证据：`/tmp/manim-rc1-alembic-empty-upgrade.log` 与临时数据库

### downgrade/upgrade 与 migration tests

- 临时库回归：`0008_asset_versions -> 0007_phase10_ir -> 0008_asset_versions`
- 退出码：两步均为 `0`；最终 current 仍为 `0008_asset_versions (head)`
- 聚焦测试：IR migration、AssetVersion DB、Phase 5–9 migration tests
- 结果：`15 passed in 4.57s`；退出码 `0`

### 契约与依赖

- `uv run python scripts/generate_contracts.py --check`：退出码 `0`，无生成漂移
- Python/Pydantic 常量、JSON Schema `$id`/extension 与 TypeScript 常量均为 contract `1.10`
- `uv sync --frozen --python 3.10 --offline`：退出码 `0`，锁定的 50 个包可由当前缓存复现
- `npm ci --ignore-scripts --offline`：退出码 `0`，安装 356 个包；audit 为 0 vulnerabilities
- 当前 `uv.lock` SHA-256：`b06b5bf8282180ab0e384f65c7da9f9c448e4fff11686559df148506bfd70d17`
- 当前 `package-lock.json` SHA-256：`1edd3fe6e59cc96b4fe601b5ba60aa6caa6318b315daa6ed57fc4d1392f02d85`
- 锁文件变化仅为已记录的 `nanoid 3.3.18` production security patch

## 2026-08-23 — 阶段 6：真实运行环境与 held-out 验收

### 环境

- Redis：隔离容器 `manim-rc1-redis`，端口 `6381`
- API：`127.0.0.1:8011`，隔离 SQLite `/tmp/manim-rc1-runtime/rc1.db`
- Runner：`rc1-readiness-runner`，真实 Docker sandbox
- Web：离线 production build，`127.0.0.1:3011`
- Provider：真实 DeepSeek，观测模型 `deepseek-v4-flash`
- 本地工作台按项目设计使用 `auth_disabled=true`；`/login` 重定向 `/workbench`，并签发 `dev@local.test` session
- 脱敏 JSON 与截图：`/tmp/manim-rc1-runtime/evidence/`；未记录 API key、Cookie 或完整请求头

### 教学旧路径

- held-out 圆面积扇形重排 Prompt：ContentPlan `ready` 5.551s，CodeVersion `ready` 9.461s，各 1 次 Provider attempt
- Preview：`succeeded`，16.219s，74 frames，854x480@15，4 个产物，MP4 可解码，下载 hash 与 descriptor 一致
- Final：`succeeded`，38.493s，288 frames，1920x1080@60，4 个产物，MP4 可解码，下载 hash 一致
- 阻塞：Preview/Final QualityReport 均为 `failed` / `0`；实际时长 4.93s/4.80s，目标 30s，同时有 `key_formula_missing` 与 timeline 诊断
- 额外 held-out 等比数列 Prompt 被 Provider 错误地要求已经明确的推导目标，保留为语义失败证据
- 证据：`/tmp/manim-rc1-runtime/evidence/teaching.json` 与 `teaching-attempt-1.json`

### 科研无资产路径

- held-out Lorenz Prompt：Intent 忠实，假设显式，`lorenz_ensemble(delta=1e-5)` 的 trajectory/divergence 断言为真
- Critic：5.0，repair 0；AnimationIR 与确定性 compiler 产物存在
- Preview：`succeeded` / 44.521s / 180 frames；Final：`succeeded` / 167.958s / 720 frames；均为真实 Docker 且 hash 一致
- 阻塞：两份 QualityReport 均 `failed` / `0`；请求目标 30s，实际为 12s，还有公式、边界和重叠诊断
- 浏览器中的第二个 held-out Fourier 任务也完成 Preview/Final，但目标 30s/实际 11.4s，QualityReport `failed` / `0`
- 证据：`research.json`、`browser.json`、`browser-final.png`

### CSV / AssetVersion 路径及修复

- 首轮发现 `timestamp` 不被接受；修复为允许 `time|timestamp`，但不改写原 AssetVersion 列 provenance
- 第二轮发现 Provider 虚构 `center=0`；改为仅从用户明确时间表达中提取 center，否则由内核从真实数据检测
- 第三轮发现 planner 仍注入 benchmark 专属 `center=350,width=20`；移除该默认，并让未显式给 width 的任务按当前数据时间间隔适配
- 还发现 API `AgentService` 忽略 `MANIM_WORKBENCH_COMPUTE_ROOT`，导致命中旧工作树缓存；已改为遵循环境隔离路径
- 最终 held-out `timestamp,temperature,pressure` CSV：6 行，异常 center=3，count=1；input/output AssetVersion `derived_from` hash 一致；Preview/Final 真实渲染成功
- 第二个 held-out `time=2` CSV：Intent params `center=2.0`，5 行，anomaly_count=1，provenance 完整
- 阻塞：首个资产视频 QualityReport 为 `failed` / `17`，实际 4.2s 低于 30s 目标
- 修复提交：`a613898 fix: harden held-out intent and CSV handling`
- 证据：`csv.json`、`csv-explicit-center-provider.json`，以及保留的修复前 JSON

### 安全停止

- 缺少 CSV：`asset_required`，`needs_confirmation=false`，0 ToolRun，无 CodeVersion
- 未提供正文的论文：`needs_confirmation`，0 ToolRun，无 CodeVersion
- 直接查询该项目权威 SQLite：0 RenderJob，0 CodeVersion，没有进入 sandbox
- 证据：`safety.json`

### 浏览器与恢复性

- Chromium production Web：创建项目、DeepSeek 生成、Preview、Final、视频预览、485,374-byte 下载、刷新后 job/video 恢复均成功
- 页面明确呈现质量失败，没有将渲染成功伪报为质量通过
- 浏览器 console 记录 18 次 404；本轮脚本未记录 URL，无法将其关闭为良性轮询，列入未解风险
- 恢复测试：Final 在 `running` 时停止 API，客户端观测 63 次暂时请求失败；API 重启后最终唯一 `succeeded`，4 个产物，无部分发布
- 首次 sandbox 完成时 API 不可用，无法确认完成；租约恢复后发生第 2 次 attempt，总耗时 166.997s。这是条件性 at-least-once 恢复，不是无条件重复，但仍是 RC1 成本风险
- 本地模式无交互登录/退出，也无法在同一 production 浏览器会话创建第二真实用户；Cookie/CSRF/owner 边界仅有自动化套件证据，不计为本轮多用户真实浏览器验收

## 阶段 7/8 当前结论

- held-out 覆盖至少 8 个真实 Provider 请求：教学≥2、无资产科研≥2、CSV≥2、模糊/缺资料≥2
- 初始失败被保留：教学错误澄清、IntentSpec schema/shape 错误、CSV 列名/伪 center/历史默认错误
- 所有真实视频的质量门禁均失败；因此结论已被确定性固定为 `NO-GO`
- 修复质量门禁需让 ContentPlan/Agent target duration 真正约束时间线，并将修复循环接入发布链；这不是可用删测试、改 benchmark 或虚报渲染成功替代的问题
- 不创建 tag，不推送；外部小范围试用阶段已按用户指示从计划中取消

## 2026-08-23 — 视频时长与发布质量闭环

### 根因与修复

- Agent API 未向 orchestrator 传递 `target_duration_seconds`，Visual Director 继续使用 4–12 秒固定模板；现由 Intent 接收请求时长并按固定开销/活跃动画权重确定性重排 IR。
- 教学源码在安全和 sandbox preflight 后直接持久化；现增加 ContentPlan 时间线/内容门禁，并复用既有最多两次有界修复，错误源码不会保存。
- `/complete` 原先先注册 Artifact，再写 QualityReport；现先生成不可变报告，缺失或 `failed` 时 Job 失败且 Artifact 表不注册任何行。
- 科研 `compiled_ir` 原先被教学公式完整性规则误伤；现只对科研执行时间与媒体视觉诊断。
- CSV 1080p60 Final 首轮返回 247/SIGKILL；根因是单个 12.9 秒 Cairo 动画触及 2 GiB sandbox 内存。现将活跃动画拆为最长 3 秒，并以单 `VMobject` 连续路径替代逐帧多 `Line` 重建。

### 自动化验证

- 聚焦与相关回归：`358 passed in 63.17s`，退出码 `0`。
- 编译器与安全边界增量复测：`34 passed`，退出码 `0`。
- `uv run ruff check .`：退出码 `0`。
- `git diff --check`：退出码 `0`。

### 真实 Docker 验收

- 证据目录：`/tmp/manim-rc1-duration-quality/`，不纳入 Git。
- held-out Lorenz Preview：目标/估算/实际 `30/30/30s`，450 帧，15 fps，无 error 诊断。
- held-out Lorenz Final：目标/估算/实际 `30/30/30s`，1800 帧，60 fps，无 error 诊断。
- 新 CSV Preview：目标/估算/实际 `30/30/30s`，450 帧，15 fps，无 error 诊断。
- 新 CSV Final：目标/估算/实际 `30/30/30s`，1800 帧，60 fps，无 error 诊断。
- 四项均保留 `object_overlap` warning，QualityReport 可发布但不隐藏告警。
- 独立 CSV Final 资源复测：退出码 `0`，真实 sandbox 渲染约 `23.08s`。

### 当前边界

- 当前 shell 未配置 `DEEPSEEK_API_KEY`，未在本次修复提交上重跑真实 Provider；不将 catalog fallback 当作 Provider 证据。
- 视频时长与 fail-closed 发布代码阻塞已关闭，但整体 RC1 仍为 NO-GO，禁止创建 tag。

### 合并前全量门禁

- 首次全量复测发现 Phase 8 黑盒假 Provider 仍用 `0.1s` 源码声明 60 秒 ContentPlan，10 个测试被新质量门禁正确拒绝；将夹具改为包含必需公式且具有 60 秒活跃时间线后，Phase 8 黑盒 `11 passed`。
- 全量 Run 1：`594 passed in 76.37s`，退出码 `0`；证据 `/tmp/manim-pytest-duration-quality-pass-1.log`。
- 全量 Run 2：`594 passed in 76.75s`，退出码 `0`；证据 `/tmp/manim-pytest-duration-quality-pass-2.log`。
- 两轮均执行真实 Docker P0，最慢项约 46 秒；均正常退出，无人工中止。
- `uv run ruff check .`、`generate_contracts.py --check`、`git diff --check`：均退出码 `0`。
- Web lint/typecheck：退出码 `0`；production build 首次受工具 sandbox 影响无法创建 `.next`，在授权的项目 worktree 环境原命令复跑后退出码 `0`，6 个静态页面生成。
