# Manim 数学动画工作台

面向教师和数学内容创作者的 AI 数学动画工作台。首版聚焦公式推导与函数可视化，采用“教学规划确认 → 完整 Manim 代码生成 → 隔离渲染 → 预览与导出”的工作流。

## 当前状态

项目已完成 Phase 0–9。现在具备账号与不可变版本、三栏工作台、SSE 恢复、鉴权产物、
完整 Manim 代码生成、隔离渲染，以及目标/估算/实际时长和确定性画面质量诊断。Phase 9 的
15 个公式与 15 个函数任务已完成 60 次真实 Preview/Final 渲染，全部为 90 秒且严重视觉项
为零；全仓 519 项 Python 测试和真实双用户浏览器门禁通过。外部真实用户市场验证仍未完成，
属于 Phase 10。

## Phase 9 验收摘要

| 门禁 | 结果 |
| --- | --- |
| 真实黄金任务 | 30 条（15 个公式推导、15 个函数可视化） |
| 真实渲染 | 30 次 Preview + 30 次 Final，共 60 次终态渲染 |
| 时间轴 | 全部 90 秒；Preview/Final 时长差为 0 |
| 质量诊断 | 严重空白、长静止、中文乱码、越界和关键对象缺失均为 0 |
| 自动化测试 | Phase 9 `85 passed`；全仓 `519 passed` |
| 浏览器与安全 | 双用户真实浏览器门禁、迁移升降级和依赖安全审计通过 |

可复核证据位于 [`benchmarks/phase9/real_acceptance_report.json`](benchmarks/phase9/real_acceptance_report.json)
和 [`benchmarks/phase9/real_terminal_records.json`](benchmarks/phase9/real_terminal_records.json)。全仓
`ruff format --check .` 尚有 50 个 Phase 2–8 历史文件需要格式化；为保护既有未提交修改，本轮未
批量改写这些无关文件。Ruff lint、Phase 9 触碰文件格式、测试、构建和运行时验收均已通过。

## 文档

- 深度研究：[`deep-research-report.md`](deep-research-report.md)
- 实施计划：[`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md)
- Phase 0 验收：[`docs/PHASE0_STATUS.md`](docs/PHASE0_STATUS.md)
- Phase 1 验收：[`docs/PHASE1_STATUS.md`](docs/PHASE1_STATUS.md)
- Phase 1 黄金集：[`eval/gold_prompts.jsonl`](eval/gold_prompts.jsonl)
- Phase 2 验收：[`docs/PHASE2_STATUS.md`](docs/PHASE2_STATUS.md)
- Phase 3 规格：[`docs/PHASE3_SPEC.md`](docs/PHASE3_SPEC.md)
- Phase 3 验收：[`docs/PHASE3_STATUS.md`](docs/PHASE3_STATUS.md)
- Phase 4 验收：[`docs/PHASE4_STATUS.md`](docs/PHASE4_STATUS.md)
- Phase 5 规格：[`docs/PHASE5_SPEC.md`](docs/PHASE5_SPEC.md)
- Phase 5 威胁模型：[`docs/PHASE5_THREAT_MODEL.md`](docs/PHASE5_THREAT_MODEL.md)
- Phase 5 验收：[`docs/PHASE5_STATUS.md`](docs/PHASE5_STATUS.md)
- Phase 6 规格：[`docs/PHASE6_SPEC.md`](docs/PHASE6_SPEC.md)
- Phase 6 威胁模型：[`docs/PHASE6_THREAT_MODEL.md`](docs/PHASE6_THREAT_MODEL.md)
- Phase 6 验收：[`docs/PHASE6_STATUS.md`](docs/PHASE6_STATUS.md)
- Phase 7 规格：[`docs/PHASE7_SPEC.md`](docs/PHASE7_SPEC.md)
- Phase 7 威胁模型：[`docs/PHASE7_THREAT_MODEL.md`](docs/PHASE7_THREAT_MODEL.md)
- Phase 7 验收：[`docs/PHASE7_STATUS.md`](docs/PHASE7_STATUS.md)
- Phase 8 规格：[`docs/PHASE8_SPEC.md`](docs/PHASE8_SPEC.md)
- Phase 8 威胁模型：[`docs/PHASE8_THREAT_MODEL.md`](docs/PHASE8_THREAT_MODEL.md)
- Phase 8 验收：[`docs/PHASE8_STATUS.md`](docs/PHASE8_STATUS.md)
- Phase 9 规格：[`docs/PHASE9_SPEC.md`](docs/PHASE9_SPEC.md)
- Phase 9 威胁模型：[`docs/PHASE9_THREAT_MODEL.md`](docs/PHASE9_THREAT_MODEL.md)
- Phase 9 验收：[`docs/PHASE9_STATUS.md`](docs/PHASE9_STATUS.md)
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

## 开发命令

```bash
uv sync --frozen
npm ci --ignore-scripts
uv run python scripts/generate_contracts.py
uv run alembic upgrade head
docker compose -f infra/compose.yaml up -d redis
uv run python scripts/create_user.py user@example.com
```

启动边界进程：

```bash
uv run uvicorn manim_workbench_api.main:app --reload
uv run python -m manim_workbench_runner run
npm run dev:web
```

运行门禁：

```bash
uv run ruff check apps/api apps/runner packages/contracts tests benchmarks scripts reference_scenes
uv run python scripts/generate_contracts.py --check
uv run pytest -s -q
npm run lint
npm run typecheck
npm run build
uv run python scripts/phase8_acceptance.py
uv run python scripts/phase9_acceptance.py
uv run python scripts/phase9_real_render_acceptance.py --workers 1
```
