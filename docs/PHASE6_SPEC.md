# Phase 6 规格：DeepSeek ContentPlan 生成

日期：2026-08-04
状态：父级冻结，允许互斥模块并行实现

## 目标

把已保存的 `PromptVersion` 转换为可由用户确认的 `ContentPlanVersion`。Phase 6
只生成教学规划，不生成或执行 Python。成功结果必须明确展示受众、语言、目标时长、
推导风格、关键假设、歧义和逐场景教学结构。

## 已批准假设

1. API 为同步生成接口；异步渲染队列不承担模型调用。
2. Provider 固定为 DeepSeek，模型固定为 `deepseek-v4-flash`，非思考模式。
3. 使用 OpenAI 兼容 Chat Completion 和 JSON Output；API Key 只从
   `DEEPSEEK_API_KEY` 环境变量读取。
4. 历史 ContentPlan 1.0 保持可读；Phase 6 新结果写为 ContentPlan 1.1。
5. 缺失的关键数学意图不得静默猜测；返回 `needs_clarification`。
6. 首版不支持几何证明、线性代数、语音、用户素材和任意代码编辑；返回
   `unsupported` 及可行替代建议。

## 生成管线

```text
HTTP request
  -> boundary schema
  -> load PromptVersion and verify project/owner
  -> deterministic prompt construction
  -> DeepSeek JSON Output
  -> JSON parse
  -> ContentPlanModelResponse schema
  -> business semantic validation
  -> append-only ContentPlanVersion + GenerationAttempt
  -> public response
```

模型输出永远是不可信输入。它不能进入 SQL、文件路径、Shell、Manim 或 Docker；只有
`ready` 且通过本地 Schema 与业务语义校验的计划才能持久化。

## Prompt 输入契约

`ContentPlanGenerationRequest`：

- `project_id`、`owner_id`、`prompt_version_id`
- `audience`：可选；未指定时模型必须返回澄清或在输出中显式说明可撤销假设
- `language`：默认 `zh-CN`
- `target_duration_seconds`：可选，范围 30–180
- `derivation_style`：可选，枚举 `step_by_step / conceptual / proof_oriented /
  visual_intuition`
- `explicit_assumptions`：最多 20 条

请求禁止携带 Provider、模型名、Base URL、API Key、系统 Prompt 或任意工具参数。
原始 Prompt 只从不可变 `PromptVersion` 加载，避免请求正文与版本记录分叉。

## DeepSeek 请求契约

- Base URL：`https://api.deepseek.com`
- Endpoint：`POST /chat/completions`
- Model：`deepseek-v4-flash`
- `thinking.type=disabled`
- `response_format={"type":"json_object"}`
- `temperature=0`
- `max_tokens=12000`
- connect/read/write/pool timeout 均有限；禁止无限等待
- User Prompt 必须包含单词 `json` 和完整输出示例
- 不发送 API Key、系统环境、其他用户数据或文件内容到消息正文

Provider 只返回原始文本、`finish_reason`、usage 和请求 ID 元数据；不承担业务校验。

## 模型响应契约

`ContentPlanModelResponse.outcome` 是判别字段：

- `ready`：必须有且只能有 `plan`
- `needs_clarification`：必须有 1–4 个结构化 `clarifications`，不得有 `plan`
- `unsupported`：必须有 1–4 个结构化 `limitations`，不得有 `plan`

`ready.plan` 使用 ContentPlan 1.1，场景号必须从 1 连续递增；每个场景有教学目标、
公式步骤、视觉意图和旁白占位。公式仅作为数据保存，不在 Phase 6 执行。

## 错误分类与用户路径

| Code | 来源 | 自动重试 | 用户路径 |
|---|---|---:|---|
| `configuration_error` | 缺少或非法 API 配置 | 否 | 管理员配置 |
| `provider_auth_error` | 401/402 | 否 | 管理员检查密钥/余额 |
| `provider_rate_limited` | 429 | 是，最多一次 | 稍后重试 |
| `provider_unavailable` | 500/503/网络超时 | 是，最多一次 | 稍后重试 |
| `provider_empty_response` | 空内容 | 是，最多一次 | 修改 Prompt 或重试 |
| `provider_truncated_response` | `finish_reason=length` | 是，最多一次 | 缩小要求或重试 |
| `provider_invalid_json` | JSON 解析失败 | 是，最多一次 | 修改 Prompt 或重试 |
| `provider_schema_error` | 响应不符合本地 Schema | 是，最多一次 | 修改 Prompt 或重试 |
| `content_plan_semantic_error` | 业务/公式静态检查失败 | 否 | 显示字段级修正建议 |
| `prompt_version_not_found` | 输入版本不存在 | 否 | 选择有效版本 |
| `ownership_mismatch` | project/owner 不一致 | 否 | 拒绝请求 |

只有表中明确标记的错误可重试；总调用次数最大 2。认证、配置、所有权和业务语义错误
不得重试。重试不改变 Prompt、模型、温度或 Schema，避免不可审计漂移。

## 持久化

- `content_plan_versions` 保持 append-only；只持久化 `ready`。
- 新记录 `schema_version=1.1`，版本号在单事务内按项目递增并连接父版本。
- 每次 Provider 调用各写一条 `GenerationAttempt`，仅保存错误 code 与版本 ID；不得保存
  API Key、Authorization header、完整模型响应或系统 Prompt。
- `needs_clarification` 和 `unsupported` 返回给调用方但不创建 ContentPlanVersion。

## 业务语义规则

1. 场景号从 1 连续递增，场景数 1–24。
2. 总计划时长与请求目标一致；显式值必须原样保留。
3. 受众、语言和推导风格必须显式。
4. 公式表达式不得为空、不得包含代码围栏、HTML/脚本或 Shell 指令。
5. 公式推导类至少有两个公式步骤；函数可视化类至少有坐标/定义域/关键行为意图。
6. 关键歧义未解决时不得返回 `ready`。
7. 不支持范围必须返回 `unsupported`，不能伪装成成功计划。

## 评分与门禁

黄金集 30 条，父 agent 使用同一 Provider 配置串行运行并保存脱敏 JSONL 报告：

- Schema 合法率 >= 95%（至少 29/30）
- 业务语义通过率 >= 90%（至少 27/30）
- 数学公式静态解析成功率 >= 95%
- 每条均有明确的成功、澄清、不支持或可行动错误路径
- 同一输入重复 3 次的结构稳定率单独统计，不通过不阻断首版，但必须写入状态报告

数学正确性人工评分沿用 `eval/README.md`：低于 4/5 直接失败。Agent D 只能读取黄金集，
不能修改生产 Prompt、Schema 或黄金条目。

## 文件所有权

| Owner | 可写范围 |
|---|---|
| 父 agent | `docs/PHASE6*`、`tasks/*`、`packages/contracts/**`、`migrations/**`、`apps/api/.../content_plans/{models,errors,repository,service,router,dependencies}.py`、`main.py`、父级/集成测试 |
| Terra A | `apps/api/.../content_plans/provider/**`、`tests/phase6/provider/**` |
| Terra B | `apps/api/.../content_plans/validation/**`、`tests/phase6/validation/**` |
| Terra C | `apps/api/.../content_plans/prompts/**`、`tests/phase6/prompts/**` |
| Terra D | `benchmarks/phase6/**`、`tests/phase6/evaluation/**` |

任何越界需求只报告给父 agent，不直接修改。

## 完成标准

- 契约生成物同步，迁移升级/降级通过。
- Provider、Prompt、业务校验、持久化和 API 集成测试全部通过。
- 密钥扫描无泄露；日志与错误响应不含 Authorization、原始密钥或完整内部异常。
- 离线 fake Provider 全绿后才运行少量真实 API smoke。
- 真实 30 条黄金集达到上述门禁并保存 `docs/PHASE6_STATUS.md`。
