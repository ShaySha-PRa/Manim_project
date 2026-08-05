# Phase 8 状态报告

日期：2026-08-05
结论：完成；真实浏览器和全仓 Ruff 遗留门禁已关闭。

## 已交付

- schema `1.4` 与 Alembic `0005`：用户密码状态、服务端 Session、登录尝试和持久 Job Event。
- 管理员 CLI 创建用户、Argon2id 哈希、登录/退出、首次登录强制改密、会话过期与撤销、登录限流。
- Project CRUD、PromptVersion、人工 ContentPlanVersion、父子链、分页历史、数据库不可变约束和 owner 隔离。
- Cookie + Origin + Session 绑定 CSRF、显式 CORS allowlist、安全响应头和稳定 API 错误语义。
- Job SSE、`Last-Event-ID` 续传、终态去重、刷新/API 重启恢复、Artifact 预览下载和路径边界。
- 共享 Web API Client，以及登录、改密、会话恢复、响应式设计系统和三栏工作台。
- 普通用户表单化编辑 ContentPlan；Python 仅可查看或下载，没有编辑和执行入口。

## 父级审查修复

- 为项目和工作区写请求补齐 Session 绑定 CSRF 与 Origin 校验。
- 将 ContentPlan/Code Provider 内部异常替换为稳定脱敏消息，同时保留管线阶段和错误码。
- 将 Artifact 读取统一收口到共享 API Client。
- 增加工作台退出入口和主内容跳转目标。
- 修正 schema `1.4` 对 Phase 5 旧断言的回归，以及黑盒夹具未声明受众导致的伪失败。
- 将 Prompt/ContentPlan 历史由无界列表改为版本游标分页，并在工作台提供加载更多入口。

## 验收证据

| 门禁 | 结果 |
|---|---|
| Phase 8 + Web 定向测试 | `67 passed`，0 failure，0 error，0 skip；连同 3 项契约生成测试共 30.658 s |
| 全仓测试 | `423 passed`，0 failure，0 error，0 skip，49.592 s |
| 双用户黑盒攻击集 | `11/11`，100%，约 13.6 s |
| 跨用户 Project/Prompt/Plan/Code/Job/SSE/Artifact | 全部返回不可枚举的拒绝结果 |
| 首次改密、退出/改密旧 Session 失效 | 通过 |
| SSE 断线续传、API 重启恢复、唯一终态 | 通过 |
| Artifact 穿越、symlink、类型混淆 | 通过 |
| 迁移 | `0005` upgrade/downgrade 与 Job Event 触发器测试通过 |
| 契约同步 | `scripts/generate_contracts.py --check` 通过 |
| 前端 | ESLint、TypeScript、Next.js production build 通过 |
| 前端依赖 | `npm audit --omit=dev`：0 vulnerability |
| Python 依赖 | `pip-audit`：No known vulnerabilities found |
| Phase 8 Ruff | check 与 format check 通过 |
| 敏感信息 | `.env` 被忽略且权限 `600`；生产代码模式扫描通过 |
| 残留运行资源 | 3000/8000/9222 无监听；Docker 无运行容器 |

离线双用户链路使用受控假 Provider 验证了 Prompt → ContentPlan → CodeVersion →
Preview/Final 的权限和状态编排。Phase 6/7 已保存的真实 DeepSeek + Docker 黄金集证据
继续作为模型与渲染质量基线，本轮没有重复消耗真实 API 配额。

## 已关闭的遗留门禁

### 真实浏览器

项目内 Playwright 1.62.1 与 Chrome 151 在隔离端口完成两个用户的首次改密、项目、
Prompt → ContentPlan → CodeVersion → Preview → Final、SSE 断线续传、API 新 PID 恢复、
视频/缩略图/下载、320/768/1024/1440 和键盘焦点验收。最终 `1 passed (1.3m)`；证据见
`docs/PHASE8_BROWSER_ACCEPTANCE.md`。

### 全仓 Ruff

Phase 2 的 212 条历史错误已在严格限定写集内清零，`ruff check .` 全通过；修复后全仓
`428 passed`。

### pip check

`pip check` 报告系统 `pygobject 3.42.1` 缺少 `pycairo`，属于宿主 Python 基线；项目锁定
依赖的 `pip-audit` 已通过。该宿主问题不影响本项目测试或运行，但全绿环境门禁需在隔离
Python 环境中复核。

## 结论与下一步

Phase 8 已完整关闭并允许进入 Phase 9。未经要求没有提交、推送或创建 PR。
