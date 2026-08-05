# Phase 9 规格：确定性质量诊断、回归与自动降级

状态：冻结
日期：2026-08-05
共享契约：1.5
迁移：0006_phase9

## 目标与硬门禁

Phase 9 把“渲染成功”提升为“可用于教学”。`target_duration_seconds` 必须从
ContentPlan 进入代码生成 Prompt、静态时间轴估算、实际 MP4 诊断和最多两次自动修复。
目标 90 秒的合格范围为 81–99 秒。结尾长静止画面不能用于凑时长。

- Preview 与 Final 使用同一源码和时间轴，帧数换算后的时长差不超过一帧。
- 静态诊断解析 `play(..., run_time=...)` 与 `wait(...)`；无法确定的调用必须显式报告。
- 渲染后读取容器时长、帧率和帧数，不信任客户端或模型声明。
- 单个动画 `run_time` 不超过 4 秒；Preview 固定 1 GiB，Final 固定 2 GiB，其他沙箱隔离
  控制保持不变。
- 暂不引入 VLM；画面采样和评分全部为确定性规则。
- 可修复问题最多两次；同一诊断签名重复出现时停止循环并降级或失败。

## 质量状态机

```text
pending → analyzing → passed
                   ├→ repair_required → repairing(1..2) → analyzing
                   ├→ degraded
                   └→ failed
```

终态为 `passed`、`degraded`、`failed`。报告 append-only；修复产生新的 CodeVersion 和新的
QualityReport，不修改旧报告。严重空白、乱码、越界或关键公式缺失不得降级为通过。

## 确定性诊断

- 时间：目标、静态估算、实际 MP4、Preview/Final 帧差、最长静止区间。
- 画面：空白、近空白、长静止、边界接触、越界、明显重叠、字号过小、乱码方框。
- 教学一致性：计划场景、公式、对象和动画顺序缺失或错序。
- 每条诊断包含稳定 code、severity、pipeline stage、数值指标、脱敏证据引用和用户建议。

## 评分与阈值

- 时长分：实际时长在目标 ±10% 内为满分；超出即 error。
- 时间轴一致性：Preview/Final 误差不超过 `1 / max(fps)` 秒。
- 静止：单段静止超过目标时长 20% 或结尾静止超过 5 秒且用于补足时长为 error。
- 视觉/教学严重项为零才可 `passed`；warning 可降级但必须展示建议。
- 总分 0–100；`passed >= 85` 且无 error，`degraded >= 70` 且仅允许降级项。

## 版本追踪

每份报告固定保存 provider model、Prompt template、ContentPlan schema、Manim 版本、镜像摘要、
AST policy 版本、诊断 policy 版本、修复次数、输入/输出 CodeVersion、Job、指标和人工评分。
相同输入与相同版本必须产生相同诊断签名。

## API 与错误语义

- `GET /api/v1/quality-reports/{id}`
- `GET /api/v1/projects/{id}/quality-reports?cursor=&limit=`
- `GET /api/v1/render-jobs/{id}/quality-report`
- `POST /api/v1/quality-reports/{id}/human-rating`

浏览器不提交 owner。不存在与跨 owner 均返回相同 404。质量错误使用 schema 1.5
`ApiErrorResponse` 和 `quality_analysis`/`quality_recovery` stage；内部日志不返回给浏览器。

## 修复矩阵

时长不足/过长、静止、越界、重叠、字号、乱码、公式/对象缺失和错序均映射到单一修复
Prompt 类别。安全违规不修复；渲染基础设施失败沿用 Phase 5 恢复；两次失败、重复签名或
不可修复严重项进入稳定降级/失败终态。

## 最终验收

30 条黄金任务各完成 Preview 和 Final（至少 60 次终态渲染）；时长误差 ±10%；
Preview/Final 不超过一帧；严重空白、乱码、越界、关键公式缺失为零；诊断可重复；版本升级
导致指标下降时门禁失败；QualityReport、证据、Job 和 Artifact 继续 owner 隔离。
