# Phase 6 威胁模型

## 信任边界与资产

边界：用户请求 -> API；数据库 Prompt -> Prompt builder；API -> DeepSeek；DeepSeek 输出 ->
本地解析/校验；校验结果 -> append-only 数据库。

资产：DeepSeek API Key、用户 Prompt、其他项目数据、系统 Prompt、模型调用预算、不可变版本
历史和后续沙箱边界。

## STRIDE 与滥用用例

| 威胁 | 滥用方式 | 强制控制 |
|---|---|---|
| Spoofing | 伪造 owner/project 读取他人 Prompt | 单查询校验三 ID 同属；不返回存在性细节 |
| Tampering | 请求覆盖模型/Base URL/系统 Prompt | 配置固定；请求 Schema `extra=forbid` |
| Repudiation | 否认高成本调用 | 每次调用写脱敏 GenerationAttempt 与 request ID |
| Information disclosure | Prompt 注入诱导输出密钥/系统 Prompt | 密钥不进消息；错误与日志字段 allowlist |
| Denial of service | 超长 Prompt、无限 token、重试风暴 | Prompt 20k 上限、12k 输出、有限 timeout、最多 2 次调用 |
| Elevation of privilege | 模型输出代码或命令进入执行器 | 输出只按数据解析；Phase 6 不接 Runner/Docker |

## 必测攻击

- 请求中注入额外 `api_key`、`model`、`base_url`、`system_prompt` 字段。
- Prompt 指令模型泄露系统提示、输出 Python/Shell、返回 HTML/script。
- Provider 返回空白、超长 JSON、截断、重复键、额外字段和类型混淆。
- Provider 返回 401、402、422、429、500、503 和网络 timeout。
- 对可重试与不可重试错误分别验证精确调用次数。
- project/owner/prompt 三元组错配。
- 确认日志、异常、评测报告和 Git diff 中没有真实密钥。

## Phase 边界

ContentPlan 中的公式和视觉意图仍是不可信文本。Phase 7 AST/import 校验完成前，任何模型
输出不得变成 Python，也不得提交给 Phase 5 沙箱。
