# Manim 数学动画工作台

面向教师和数学内容创作者的 AI 数学动画工作台。首版聚焦公式推导与函数可视化，采用“教学规划确认 → 完整 Manim 代码生成 → 隔离渲染 → 预览与导出”的工作流。

## 当前状态

项目已完成 Phase 0–3。Phase 1 形成并复核了 30 条代理用户黄金 Prompt；Phase 2 通过真实无头渲染选择 Manim Community `0.20.1`，ManimGL 已淘汰；Phase 3 建立了契约优先的 Web、API、Runner、SQLite 与 CI 骨架。外部真实用户市场验证尚未完成。

## 文档

- 深度研究：[`deep-research-report.md`](deep-research-report.md)
- 实施计划：[`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md)
- Phase 0 验收：[`docs/PHASE0_STATUS.md`](docs/PHASE0_STATUS.md)
- Phase 1 验收：[`docs/PHASE1_STATUS.md`](docs/PHASE1_STATUS.md)
- Phase 1 黄金集：[`eval/gold_prompts.jsonl`](eval/gold_prompts.jsonl)
- Phase 2 验收：[`docs/PHASE2_STATUS.md`](docs/PHASE2_STATUS.md)
- Phase 3 规格：[`docs/PHASE3_SPEC.md`](docs/PHASE3_SPEC.md)
- Phase 3 验收：[`docs/PHASE3_STATUS.md`](docs/PHASE3_STATUS.md)
- 渲染引擎 ADR：[`docs/decisions/0001-select-manim-community.md`](docs/decisions/0001-select-manim-community.md)
- 执行清单：[`tasks/todo.md`](tasks/todo.md)

## 开发边界

- 首版只支持公式推导与函数可视化。
- 默认模型为 `deepseek-v4-flash`。
- 用户可只读查看生成的 Python，不能在线修改执行。
- 所有生成代码必须通过静态校验并在一次性隔离容器中运行。
- 每个 Phase 必须通过门禁后才能进入下一阶段。

## 环境

目标开发环境为 Windows + WSL2 + Docker Desktop。仓库应放在 WSL 原生文件系统，例如 `/home/developer/projects/Manim_project`；不要从 `/mnt/c` 或 `/mnt/i` 运行 Node 安装与构建。复制 `.env.example` 为本地 `.env` 后填写密钥；任何真实密钥都不得提交到 Git。

## Phase 3 开发命令

```bash
uv sync --frozen
npm ci --ignore-scripts
uv run python scripts/generate_contracts.py
uv run alembic upgrade head
docker compose -f infra/compose.yaml up -d redis
```

启动边界进程：

```bash
uv run uvicorn manim_workbench_api.main:app --reload
uv run python -m manim_workbench_runner
npm run dev:web
```

运行门禁：

```bash
uv run ruff check apps packages scripts/generate_contracts.py tests/phase3 migrations
uv run pytest -q
npm run lint
npm run typecheck
npm run build
```
