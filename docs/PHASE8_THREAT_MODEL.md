# Phase 8 STRIDE 威胁模型

日期：2026-08-05
结论：浏览器、LLM 输出、Cookie、SSE 游标和 Artifact 标识均是不可信输入。

| 边界 | STRIDE 风险 | 失败关闭控制 | 验证 |
|---|---|---|---|
| 登录 | 冒充、枚举、爆破 | Argon2id、统一错误、持久限流、禁用检查 | 错误矩阵与限流测试 |
| Cookie Session | 固定、窃取、重放 | 高熵令牌、只存摘要、HttpOnly、SameSite、Secure、轮换与撤销 | 固定/退出/改密测试 |
| 变更请求 | CSRF、Origin 欺骗 | Origin allowlist + Session 绑定 CSRF Token | 缺失/错误/跨站测试 |
| 资源 ID | IDOR、存在性泄漏 | 每次查询同时绑定 owner；跨用户统一 404 | 双用户交叉矩阵 |
| ContentPlan 编辑 | 篡改历史 | append-only 新版本、父版本与 owner 校验 | UPDATE/DELETE 失败测试 |
| SSE | 越权订阅、重放、DoS | owner 查询、数值游标上限、心跳、终态关闭、连接上限 | 断线与越权测试 |
| Artifact | 路径遍历、符号链接逃逸、泄漏 | DB allowlist、根目录 realpath、拒绝 symlink、MIME allowlist | 攻击语料 |
| Python 查看 | XSS、在线执行 | `text/plain`、attachment 下载、CSP、无提交端点 | 浏览器和路由矩阵 |
| 错误与日志 | 密钥、路径、跨租户泄漏 | 稳定错误码、阶段枚举、无栈与宿主路径 | 敏感扫描 |
| 服务重启 | 状态丢失、重复终态 | DB Session/Version/Job Event，唯一 `(job,state_version)` | 重启恢复测试 |

## 安全不变量

1. 未认证请求不能读取任何业务资源。
2. `must_change_password=true` 的会话只能访问改密、会话和退出。
3. Browser API 不接受或信任 `owner_id`。
4. 任何资源先按 owner 查询，再执行业务动作；不存在和不属于当前用户均返回相同 404。
5. SSE 和 Artifact 不因持有 UUID 获得授权。
6. 旧 Session 在退出、改密、禁用或过期后不可恢复。
7. 所有 LLM 产物继续经过 Phase 6/7 校验和 Phase 5 沙箱，不因 Web 接入降级。

## 暂不支持

- 公开注册、密码找回、邮件验证、OAuth、共享项目、管理员 Web 面板和用户上传文件。
