# Implementation Plan: Phase 8 Web 工作台、账号与版本系统

## Overview

父 agent 冻结 schema 1.4、0005、公共错误、安全策略和 Phase 5–7 编排；六个 Terra
agent 分两批完成互斥的认证、项目版本、交付、Web 外壳、三栏工作台和独立黑盒验收。

## Dependency Graph

```text
父规格/威胁模型/契约/迁移/红灯测试
        ├── A 认证与 Session
        ├── B 项目与不可变版本
        └── C SSE 与 Artifact
                  ↓
            父级中间集成门禁
        ├── D 登录与设计系统
        ├── E 三栏工作台
        └── F 黑盒与浏览器验收
                  ↓
       父级 Phase 5–7 集成与最终门禁
```

## Slice 0：父级冻结

- [x] 保护 Phase 0–7 未提交修改并运行基线门禁。
- [x] 固化 Phase 8 规格、STRIDE 威胁模型和状态机。
- [x] 固化 schema 1.4、0005、API 错误和 owner/CSRF/Artifact 边界。
- [x] 生成共享契约并确认父级红灯测试精确失败。

## Slice 1：第一批后端 Agent

- [x] Terra A：账号、认证、Session、管理员 CLI 和限流。
- [x] Terra B：Project CRUD、Prompt/ContentPlan 不可变版本与分页。
- [x] Terra C：SSE 重连、Artifact 预览下载和阶段错误映射。
- [x] 父 agent 审查写集、修复安全发现并通过中间门禁。

## Slice 2：第二批 Web 与验收 Agent

- [x] Terra D：登录、首次改密、全局布局和设计系统。
- [x] Terra E：三栏工作台、版本、任务、视频和 Python 只读面板。
- [x] Terra F：双用户攻击集、故障注入和浏览器验收计划。
- [x] 执行真实浏览器响应式、键盘、恢复和双用户端到端验收。

## Slice 3：父级集成与最终门禁

- [x] 提供共享 Web API Client 并集成 Phase 5–7 浏览器编排。
- [x] 记录 Job Event，证明 SSE 重连和终态幂等。
- [x] 以独立黑盒完成两个用户端到端流程及 API 重启恢复。
- [x] 运行全仓测试、契约、迁移、前端、依赖和敏感信息门禁。
- [x] 清理全仓历史 Ruff 基线并完成真实浏览器门禁。
- [x] 保存 Phase 8 状态并更新 Project Plan、README 和 todo。

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| 未提交 Phase 5–7 被覆盖 | 严格写集、父级独占共享文件、每批审查 status/diff |
| 浏览器 owner 注入 | Browser DTO 无 owner，Session 唯一推导 |
| Cookie 被 CSRF 利用 | SameSite + Origin allowlist + Session 绑定 CSRF |
| SSE 越权或重复终态 | owner 查询、持久 Event ID、唯一状态版本 |
| Artifact 路径逃逸 | DB ID allowlist + realpath 根约束 + 拒绝 symlink |
| 前后端类型漂移 | schema 1.4 生成 TypeScript，父级独占 API Client |

## Open Questions

- 无；本轮用户指令已授权认证、迁移和安全策略，未授权提交或推送。

# Implementation Plan: Phase 9 质量诊断、回归与自动降级

## Slice 0：父级冻结

- [x] 关闭 Phase 8 真实浏览器与全仓 Ruff 遗留门禁。
- [x] 冻结目标时长、质量状态机、阈值、错误、两次修复和降级矩阵。
- [x] 冻结 schema 1.5、0006 append-only 迁移及 RED→GREEN 父级测试。

## Slice 1：第一批 Terra

- [x] A：AST 时间轴、静态/实际时长和 ContentPlan 一致性。
- [x] B：确定性帧采样、空白/静止/越界/重叠/字号/乱码。
- [x] C：质量报告、诊断、provenance、人工评分和 owner 隔离。
- [x] 父 agent 审查并完成 API/Runner 中间集成门禁。

## Slice 2：第二批 Terra

- [x] D：最多两次修复、重复签名熔断和分类降级。
- [x] E：30 条黄金集、失败注入、重复性、性能与版本回归。
- [x] F：质量状态、指标、诊断和建议 Web UI。

## Slice 3：父级最终验收

- [x] 集成 Phase 5–8、真实 MP4 诊断、Preview/Final 一帧一致性。
- [x] 完成至少 60 次终态渲染和 30 条黄金任务。
- [x] 运行全仓、迁移、契约、前端、安全、敏感扫描并保存状态。
