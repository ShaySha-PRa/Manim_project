# Phase 9 验收状态

状态：完成
日期：2026-08-05
共享契约：1.5
迁移：`0006_phase9`

## 已交付

- `target_duration_seconds` 已贯穿 ContentPlan、代码生成 Prompt、Runner lease、静态时间轴、
  实际 MP4 诊断、QualityReport 和修复策略。
- 代码生成要求显式 `run_time`/`wait`、单段动画不超过 4 秒；确定性降级模板按教学节拍
  分配完整目标时长，不使用结尾静止填充。
- Runner 以 PyAV 16.1.0 做安全媒体探测和确定性帧采样，记录实际时长、FPS、帧数及脱敏
  视觉诊断，并在发布后刷新 metadata 哈希。
- API 提供 owner 隔离的 QualityReport、诊断、项目历史、Job 最新报告和人工评分接口；报告、
  诊断和评分均 append-only。
- 自动恢复策略最多修复两次，重复诊断签名立即熔断；安全和基础设施失败不会进入模型修复。
- Web 工作台已接入质量面板，展示目标/估算/实际时长、管线阶段、修复次数、诊断和建议。

## 真实黄金集验收

真实验收器：`scripts/phase9_real_render_acceptance.py`

- 15 个公式任务、15 个函数任务。
- 每项均实际执行 Preview 和 Final，共 60 次终态渲染。
- 全部实际时长为 90.0 秒；Preview 1350 帧/15 FPS，Final 5400 帧/60 FPS。
- 30 对 Preview/Final 时间轴差为 0，满足不超过一帧。
- 严重空白、中文乱码、对象越界、关键公式/对象缺失均为 0。
- 最终报告：`benchmarks/phase9/real_acceptance_report.json`，状态 `passed`。
- 终态记录：`benchmarks/phase9/real_terminal_records.json`，60 条。

并发试跑暴露 Final 资源争抢，最终以串行恢复补齐。Preview 继续固定 1 GiB；Final 在保持无网络、
非 root、只读根、cap-drop、单 CPU 和 PID 限制的前提下固定为 2 GiB。单个长动画曾触发 OOM，
现通过小于等于 4 秒的教学动画分段解决。被拒绝的 G07 v1 证据保存在
`runtime/phase9-real-acceptance-rejected-G07-v1`，未计入通过结果。

## 自动化与安全门禁

- Python：`519 passed`（pytest 9.0.3）。
- Phase 9：`85 passed`，其中包含 2 项真实渲染记录黑盒断言。
- Ruff lint、契约同步和 `git diff --check`：通过。
- Alembic：`head → 0005_phase8 → head` 通过。
- Web：lint、typecheck、production build 通过。
- 真实浏览器：双用户完整工作流、恢复、SSE、Artifact、响应式和键盘验收 `1 passed`。
- 依赖：pip-audit 与 npm audit 均为 0 个已知漏洞。
- 生产代码敏感串扫描：0 命中；测试目录中的密钥样式字符串均为脱敏 canary。

## 已知基线

全仓 `ruff format --check .` 仍报告 50 个 Phase 2–8 历史文件未格式化。为遵守“保护现有未提交
修改、不得整理无关改动”，Phase 9 未批量改写这些历史文件；Phase 9 和本阶段实际触碰文件的
格式检查已通过。这不影响 Ruff lint、测试、构建或运行时验收。

## 下一阶段

Phase 10 才进行 5–10 位外部真实用户的小范围试用。Phase 1 的代理访谈和 Phase 9 的真实渲染
不能替代真实市场验证。
