# Phase 6 状态：DeepSeek ContentPlan 生成

日期：2026-08-04
结论：通过

## 已交付

- ContentPlan 1.1、显式推导风格/假设/歧义，以及
  `ready / needs_clarification / unsupported` 判别式契约。
- 固定 `deepseek-v4-flash` 的非思考 JSON Output Provider；密钥只从
  `DEEPSEEK_API_KEY` 读取，单次 Provider 调用不自行重试。
- 父级最多两次调用的重试策略，以及空白、截断、非法 JSON、Schema、语义、认证、
  限流和不可用错误分类。
- 确定性 System/User Prompt、用户文本数据边界和结构化澄清/不支持路径。
- 场景连续性、显式字段保真、公式注入/平衡、推导步数和函数视觉意图校验。
- append-only ContentPlan 持久化、脱敏 GenerationAttempt 用量元数据和 0003 迁移。
- 内部令牌保护的 `POST /api/v1/content-plans/generate`。
- 30 条固定门禁、五类失败注入、三次结构稳定率和脱敏 JSONL 评测器。

## 父级审查修复

- 强制模型保留请求中的全部显式假设。
- 将 Provider 原始内容限制为 200,000 字符。
- 对外统一 Prompt 不存在与所有权错配响应，消除资源存在性侧信道。
- 修复 SQLite batch migration 重建表时丢失 append-only trigger 的回归。
- 更新共享契约 schema 1.2 和既有健康/生成契约回归预期。

## 最终验收证据

- Phase 6：`78 passed`。
- 全仓：`246 passed`。
- Phase 6 变更范围 Ruff：通过。
- 生成契约同步检查、迁移升级/降级、`git diff --check`：通过。
- 高熵 DeepSeek key / Authorization 扫描：未在仓库中发现。
- 4 个 Terra agent 均只修改授权文件范围。
- 新 Key 只保存在 Git 忽略的 `.env`，文件权限收紧为 `600`；真实密钥未进入命令行、
  报告、日志、测试或子 agent 上下文。

## 真实 DeepSeek 门禁

- 1 条真实 smoke：Schema、语义、公式和可行动结果均为 `1/1`。
- 最终 30 条黄金集：Schema `30/30`、业务语义 `29/30`、公式解析 `30/30`、
  可行动结果 `30/30`，`gates_passed=true`。
- 3 次重复性运行（共 90 次生成）：Schema `30/30`、业务语义 `29/30`、公式解析
  `30/30`、可行动结果 `30/30`，`gates_passed=true`。
- 重复性运行的结构稳定率为 `5/30 = 16.7%`。它按冻结规格不阻断 Phase 6，但说明
  同一 Prompt 的场景数量或结构形状经常变化，Phase 7 不得把场景结构稳定性当作隐含前提。

本地脱敏证据位于（已由 `.gitignore` 排除）：

- `runtime/phase6-real/smoke-20260804.jsonl`
- `runtime/phase6-real/gold-v5-20260804.jsonl`
- `runtime/phase6-real/stability-v1-20260804.jsonl`

首轮失败及诊断报告也被保留，便于复盘 Prompt 和语义校验器演进；所有报告都不包含
原始 Prompt、模型原文、Authorization 或 API Key。

## Phase 7 入口条件

Phase 6 已满足。Phase 7 必须继续把模型输出视为不可信输入，并针对低结构稳定率使用
Schema/语义驱动的代码生成，不能依赖固定场景数量或固定 JSON 数组形状。
