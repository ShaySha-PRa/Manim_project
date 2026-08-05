# Phase 7 规格：完整 Python 生成、校验与修复

## 目标

将已确认且持久化的 ContentPlan 1.1 转换为一个完整、可审计的 Manim Community
`0.20.1` Scene。模型输出始终是不可信输入；只有通过本地 Schema、AST、安全、编译和
Scene 结构校验的源码才能提交给 Phase 5 一次性 Docker 沙箱。

Phase 7 仅覆盖 `formula_derivation` 和 `function_visualization` 两类内容，不增加用户认证、
Web 编辑器、语音、网络访问或任意 Python 执行能力。

## 固定命令

```bash
uv run python scripts/generate_contracts.py
uv run python scripts/generate_contracts.py --check
uv run alembic upgrade head
uv run pytest -s -q tests/phase7
uv run pytest -s -q
uv run ruff check apps/api apps/runner packages/contracts tests/phase7 benchmarks/phase7
```

真实模型和渲染验收只能由父 agent 串行执行，并从本地 `.env` 读取密钥。报告不得保存
原始 Prompt、模型原文、源码、宿主路径、Authorization 或 API Key。

## 输入契约

`CodeGenerationRequest` 必须包含：

- `project_id`、`owner_id`、`prompt_version_id`、`content_plan_version_id`；
- `category`，仅为 `formula_derivation` 或 `function_visualization`；
- 可选 `force_regenerate`，默认 `false`。

Repository 必须验证四个 ID 属于同一 project/owner，ContentPlan 为 Schema 1.1 且已经
持久化。不得接受客户端直接提交 ContentPlan JSON 或参考 Scene 路径。

## 模型响应契约

模型仅返回 JSON：

```json
{
  "scene_class": "GeneratedScene",
  "code": "from manim import *\n...",
  "assumptions": []
}
```

- 仅接受 `GeneratedScene`；
- `code` 为 1–200000 字符，不接受 Markdown fence；
- `assumptions` 最多 20 项，每项最多 200 字符；
- JSON 之外的文字、未知字段和截断响应均失败；
- ContentPlan 场景数和结构不能作为稳定前提。

## 状态机与尝试预算

```text
received -> generating -> validating -> rendering -> ready
                    |           |           |
                    +-----------+-----------+-> repairable_failure
                                                     |
                         attempts < 3 -> repairing --+
                         attempts = 3 -> failed

security_violation -> blocked
provider_auth/configuration -> failed
category degraded -> deterministic_template -> validating -> rendering
global security pause -> paused
```

一次请求最多三次有效模型响应：一次初始生成和两次修复。每个生成阶段允许最多两次仅针对
限流或暂时不可用的传输重试；该重试不消费修复预算。Provider 认证/配置错误、高风险安全
违规、用户取消、基础设施不可用均不消耗修复次数。高风险安全违规不允许把候选源码发送
给修复模型，只能拒绝并记录安全错误码。仅由未知 Manim 符号/方法、禁用 lambda、Scene
结构或不支持语法节点组成的静态契约偏差可进入无源码修复：只发送稳定规则码和符号名，
候选源码仍不得回传模型或进入沙箱。

## 静态安全策略

### 顶层白名单

- `from manim import ...`；
- `import math` 或 `from math import ...`；
- `import numpy as np` 或受限 `from numpy import ...`；
- 字面量常量赋值；
- 恰好一个继承 `Scene` 的 `GeneratedScene` 类。

### 明确禁止

- 文件、网络、进程、线程、信号、序列化、环境变量和动态加载；
- `os`、`sys`、`pathlib`、`subprocess`、`socket`、`requests`、`urllib`、`httpx`、
  `shutil`、`tempfile`、`pickle`、`marshal`、`importlib`、`builtins`；
- `eval`、`exec`、`compile`、`open`、`input`、`__import__`、`breakpoint`；
- dunder 名称或属性、反射 API、任意装饰器、异步、lambda、yield、global/nonlocal；
- 星号导入（`from manim import *` 除外）、相对导入、未知 Manim API；
- 超过 200000 字符、AST 节点数 12000、字面量容器 2000 项或嵌套深度 80。

AST 校验是准入门，不是沙箱替代品。通过后仍必须进入 Phase 5 的 `--network none`、只读、
非 root、资源受限的一次性容器。

## 预检、错误分类和脱敏

预检顺序固定为：响应 Schema -> AST/安全 -> `compile()` -> Scene 结构 -> Phase 5 沙箱。
生产代码不得执行模型源码进行预检。

AST 首轮只报告漏导入、且符号已在固定 Manim 白名单中时，允许把该符号确定性补入现有
`from manim import ...`，随后必须从头重跑 AST/安全门。该规范化不得新增模块、任意符号或
跳过校验，也不消费模型修复预算。

公开错误只返回稳定机器码和安全消息。可修复诊断只保留：阶段、错误类型、候选源码中的
行号、最多 20 行/4000 字符的清洗片段。必须移除绝对路径、URL、环境变量值、Bearer
令牌和类似 API Key 的字符串。数据库只保存错误码、候选 SHA-256 和脱敏诊断摘要哈希，
不保存完整内部日志。

## 修复矩阵

| 错误类别 | 自动修复 | 消耗预算 | 发送给模型的内容 |
|---|---:|---:|---|
| 响应 JSON/Schema、Python 语法 | 是 | 是 | 原 ContentPlan、固定契约、脱敏诊断 |
| Scene 结构、允许 API 参数、普通渲染错误 | 是 | 是 | 原 ContentPlan、前一候选源码、脱敏诊断 |
| 第三次仍为已确认的 LaTeX DVI 转换错误 | 否；确定性 MathTex -> Text 降级 | 否 | 不再调用模型；重新执行 AST、预检和沙箱，并标记 degraded |
| 低风险静态契约偏差（未知 Manim 符号/方法、lambda、Scene 结构、不支持语法） | 是 | 是 | 原 ContentPlan、固定契约、规则码和符号名；不发送候选源码 |
| 高风险 AST/import/调用/属性安全违规 | 否 | 否 | 不发送候选源码 |
| Provider 认证/配置、内部错误 | 否 | 否 | 不发送 |
| 沙箱超时/OOM/输出限制 | 否 | 否 | 进入类别统计或确定性降级 |

## 类别降级矩阵

- 每类维护 `active`、`degraded`、`paused` 状态和连续失败轮数；
- 某类连续两轮最终门禁未达标：该类进入 `degraded`，改用确定性模板编译；
- 另一类保持独立，不受影响；
- 任一安全攻击漏过静态门或沙箱：两类同时 `paused`；
- 恢复必须由父级完成安全复核并显式修改策略状态，不能自动恢复；
- 确定性模板输出仍必须经过同一 AST、预检和沙箱链路。

## 持久化与 API

- `POST /api/v1/code-generations`：同步生成、校验并创建不可变 CodeVersion；
- `GET /api/v1/code-versions/{id}`：按 owner/project 读取只读版本；
- 失败只记录 GenerationAttempt，不创建 CodeVersion；
- CodeVersion 保存 category、generation mode、模板版本、provider model 和 assumptions；
- 每个候选记录 attempt number、stage、状态、错误码、候选 SHA-256 和诊断摘要哈希；
- API 延续 `{"error":{"code":"...","message":"..."}}` 错误格式。

## 子 agent 文件所有权

- Agent A：`code_generation/prompts/**`、`tests/phase7/prompts/**`；
- Agent B：`code_generation/security/**`、`tests/phase7/security/unit/**`；
- Agent C：`code_generation/validation/**`、`tests/phase7/validation/**`；
- Agent D：`code_generation/repair/**`、`tests/phase7/repair/**`；
- Agent E：`benchmarks/phase7/**`、`tests/phase7/blackbox/**`；
- 父 agent：共享契约、迁移、`code_generation` 根级 models/errors/provider/repository/service/
  router/dependencies、现有 Phase 5/6 文件、父级和集成测试、文档。

任何子 agent 不得修改另一 agent、父级或已有 Phase 0–6 的文件范围。

## 验收门禁

- 30 条黄金集首次渲染成功率不低于 75%；
- 最多两次修复后渲染成功率不低于 90%；
- 安全攻击集拦截率 100%，且零候选绕过 AST 直接进入沙箱；
- 数学正确性评分不低于 4/5 的样例占比不低于 90%；
- 视觉清晰度评分不低于 4/5 的样例占比不低于 80%；
- 重复运行中尝试预算、错误分类、源码哈希和策略状态可复现；
- Phase 0–6 全仓测试、契约生成、迁移往返和 Ruff 全部通过。

## 边界

- Always：先验证、后执行；失败关闭；日志和报告脱敏；保持版本不可变。
- Ask first：新增依赖、放宽白名单、改变沙箱策略或门禁。
- Never：提交 `.env`/密钥/模型原文/生成源码/视频；在宿主执行模型源码；让 Prompt
  充当安全边界；因修复方便而放宽静态策略。
