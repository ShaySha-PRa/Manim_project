# Phase 7 状态：完整 Python 生成、校验与修复

日期：2026-08-05
结论：通过

## 已交付

- ContentPlan 到单一 `GeneratedScene` 的完整 Manim Python 生成 Prompt、参考 Scene 注入和
  DeepSeek JSON 响应解析。
- AST、import、函数调用、属性访问和 Manim API 失败关闭白名单；所有模型源码必须先通过
  静态安全门，才允许进入 Phase 5 一次性 Docker 沙箱。
- Python 编译、Scene 结构预检、稳定错误分类，以及最多 20 行、4,000 字符的脱敏诊断。
- 初始生成加最多两次修复的有界状态机；高风险安全失败不可修复，安全类别失败可暂停全部
  代码生成，渲染兼容问题可进入确定性模板降级。
- append-only GenerationAttempt、不可变 CodeVersion、schema 1.3、Alembic 0004 迁移，
  以及代码生成 API 与 Phase 5/6 编排。
- 30 条真实黄金集评测器、8 个黑盒攻击、失败注入、离线重复性和质量/性能统计。

## 五个 Terra agent 与父级审查

- Agent A–E 分别完成生成、静态安全、预检诊断、修复降级和独立评测，文件范围互不重叠。
- 父 agent 合并共享契约、API、持久化及 Phase 5/6 边界，并完成全量代码审查。
- 审查中补齐了允许 import 的确定性归一化、真实失败日志回收与尾部保留、Provider 传输
  重试边界、参考 Scene 的 `GeneratedScene` 归一化，以及 MathTex 失败后的 Text 降级。
- 高风险安全违规始终直接终止；低风险静态契约偏差只能在不携带原始源码的条件下修复。

## 最终真实验收

30 条黄金集使用真实 DeepSeek 和真实 Docker 串行运行一次：

- 首次渲染：`27/30 = 90.0%`，门禁为 75%。
- 最终渲染：`28/30 = 93.3%`，门禁为 90%。
- 数学质量不低于 4/5：`28/30 = 93.3%`，门禁为 90%。
- 视觉质量不低于 4/5：`28/30 = 93.3%`，门禁为 80%。
- 性能：平均 `24.67 s`、P95 `32.48 s`、最大 `173.22 s`。
- 两条样例最终为 `internal_error`，但五项冻结门禁全部通过；该结果未被隐藏或改写。

安全攻击集为 `8/8 = 100%` 拦截，沙箱绕过 `0`，安全门禁通过。真实黄金集本轮
`repetitions=1`；重复性、失败注入和两次预算边界由离线固定测试覆盖，不把本轮结果表述为
三次真实重复运行。

本地脱敏证据位于（已由 `.gitignore` 排除）：

- `runtime/phase7-real/gold-v4-20260805.jsonl`
- `runtime/phase7-real/gold-attacks-v4-20260805.jsonl`
- `runtime/phase7-real/gold-v4-20260805.stdout`

## 工程与安全门禁

- 全仓测试：`356 passed`。
- Phase 7 及相关变更 Ruff：通过。
- 生成契约同步检查与迁移升级/降级测试：通过。
- Web lint、TypeScript typecheck、生产构建：通过。
- `.env` 被 Git 忽略且权限为 `600`；最终报告和 Git 差异未发现 API Key、Authorization、
  原始 Prompt、生成源码、完整诊断或宿主机路径。
- 最终检查没有残留 Docker 容器。

## Phase 8 入口条件

Phase 7 已满足。Phase 8 可以在现有代码生成 API、不可变版本和异步 Job 生命周期上构建
工作台；前端不得绕过 ContentPlan 确认、静态安全门或一次性沙箱边界。
