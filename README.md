# Manim 数学动画工作台

面向教师和数学内容创作者的 AI 数学动画工作台。首版聚焦公式推导与函数可视化，采用“教学规划确认 → 完整 Manim 代码生成 → 隔离渲染 → 预览与导出”的工作流。

## 当前状态

项目已完成 Phase 0，并通过 Phase 1 代理用户内部开发门禁：3 个 Luna 面板提供 6 个 Persona，形成并复核了 30 条黄金 Prompt。外部真实用户市场验证尚未完成。

## 文档

- 深度研究：[`deep-research-report.md`](deep-research-report.md)
- 实施计划：[`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md)
- Phase 0 验收：[`docs/PHASE0_STATUS.md`](docs/PHASE0_STATUS.md)
- Phase 1 验收：[`docs/PHASE1_STATUS.md`](docs/PHASE1_STATUS.md)
- Phase 1 黄金集：[`eval/gold_prompts.jsonl`](eval/gold_prompts.jsonl)
- 执行清单：[`tasks/todo.md`](tasks/todo.md)

## 开发边界

- 首版只支持公式推导与函数可视化。
- 默认模型为 `deepseek-v4-flash`。
- 用户可只读查看生成的 Python，不能在线修改执行。
- 所有生成代码必须通过静态校验并在一次性隔离容器中运行。
- 每个 Phase 必须通过门禁后才能进入下一阶段。

## 环境

目标开发环境为 Windows + WSL2 + Docker Desktop。复制 `.env.example` 为本地 `.env` 后填写密钥；任何真实密钥都不得提交到 Git。
