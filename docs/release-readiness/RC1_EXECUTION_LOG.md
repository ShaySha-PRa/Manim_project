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
