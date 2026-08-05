# Phase 8 规格：Web 工作台、账号与不可变版本

状态：冻结
日期：2026-08-05
共享契约：1.4
迁移：0005_phase8

## 目标

教师和数学内容创作者无需接触 JSON 或编辑 Python，即可在受控 Web 工作台完成
Prompt → ContentPlan 确认 → CodeVersion → Preview → Final，并在刷新、关闭浏览器及服务
重启后恢复项目、版本和任务状态。

## 技术栈与命令

- Web：Next.js 16.3、React 19.2、TypeScript 5.9。
- API：FastAPI、SQLAlchemy、SQLite（开发基线）、Alembic。
- 密码：Argon2id；会话：数据库持久化不透明 Cookie。
- 测试：`uv run pytest -s -q tests/phase8`、`npm run lint`、`npm run typecheck`、
  `npm run build`。

## 冻结架构

- Phase 5–7 内部令牌接口保持兼容；浏览器只调用 Phase 8 Session 接口。
- 浏览器契约不接受 `owner_id`；owner 只能由有效 Session 推导。
- Session Cookie 为 HttpOnly、SameSite=Lax；生产模式 Secure。所有变更请求还必须通过
  Origin allowlist 与 `X-CSRF-Token` 校验。
- Session 令牌和 CSRF 令牌仅以 SHA-256 摘要持久化；退出、改密和禁用账号会撤销 Session。
- 初始密码由管理员 CLI 写入；不存在公开注册接口；首次登录只能访问会话、退出和改密。
- PromptVersion、ContentPlanVersion 和 CodeVersion append-only。人工编辑 ContentPlan 必须创建
  带 parent 的新版本，禁止原地更新。
- Job Event 按数据库自增 ID 持久化；SSE 的 `id` 等于 Event ID，重连严格从
  `Last-Event-ID` 之后继续，不重复终态。
- Artifact 必须先按 `artifact_id + owner_id` 查询，再在配置的 Artifact 根目录内解析；禁止
  客户端路径、绝对路径、符号链接逃逸和目录遍历。
- Python 仅通过 `text/plain` 的只读查看/下载接口交付；无任何浏览器源码提交或执行接口。

## 状态机

### 登录与会话

```text
anonymous → authenticated_must_change → authenticated_ready
     ↑             │                         │
     └── logout / expire / revoke / password change ──┘
```

- 认证失败统一返回相同错误，避免账号枚举。
- 登录按规范化邮箱摘要和来源地址摘要进行持久化窗口限流。
- 改密成功撤销该用户所有旧 Session，再签发一个新 Session。

### 不可变版本

```text
PromptVersion(n) → ContentPlanVersion(n) → CodeVersion(n) → RenderJob
                         │
                         └── edit → ContentPlanVersion(n+1, parent=n)
```

### SSE 重连

```text
connect(last=0) → replay(id>0) → live poll → terminal event → close
disconnect(last=N) → reconnect → replay(id>N)
```

## 公开 API

- `POST /api/v1/auth/login`、`POST /api/v1/auth/logout`、`GET /api/v1/auth/session`、
  `POST /api/v1/auth/change-password`。
- `GET/POST /api/v1/projects`、`GET/PATCH /api/v1/projects/{id}`。
- `GET/POST /api/v1/projects/{id}/prompt-versions`。
- `GET/POST /api/v1/projects/{id}/content-plan-versions`。
- 浏览器侧 ContentPlan/CodeVersion/Render 编排接口由父 agent 集成现有 Phase 5–7 服务。
- `GET /api/v1/render-jobs/{id}/events`（SSE）。
- `GET /api/v1/artifacts/{id}`、`GET /api/v1/artifacts/{id}/download`。

所有错误使用 schema 1.4 `ApiErrorResponse`；管线错误必须带 `stage`，认证错误不得泄露资源
是否存在。

## 测试策略

- 单元：密码、Session、CSRF、owner 查询、游标、路径解析、SSE 编码。
- 集成：迁移升降级、认证、项目版本、Job 重连、Artifact 下载、Phase 5–7 编排。
- 黑盒：两个用户交叉访问矩阵、Session 固定、CSRF、路径穿越、SSE 断线和服务恢复。
- 浏览器：完整两用户流程、刷新恢复、键盘、可访问树、四个断点、控制台和网络。

## 成功门禁

- 两个用户分别完成 Prompt → ContentPlan → CodeVersion → Preview → Final。
- 跨用户 Project、Version、Job、SSE、Artifact 访问 100% 拒绝且无存在性侧信道。
- 首次登录强制改密；退出或改密后旧 Session 失效。
- 刷新、浏览器关闭和服务重启后数据及任务状态可恢复。
- 普通流程无 JSON；Python 只读且不可提交执行。
- SSE 无重复终态，失败消息指出管线阶段。
- 全仓测试、Ruff、契约、迁移、前端构建、依赖审计和敏感信息扫描通过。

## 边界

- 始终：边界校验、参数化 SQL、owner 查询、输出编码、脱敏错误和安全响应头。
- 本轮已授权：0005 迁移、认证依赖、Cookie/CORS/CSRF/限流实现。
- 禁止：公开注册、JWT/localStorage Token、客户端 owner、在线 Python 编辑执行、远程提交。
