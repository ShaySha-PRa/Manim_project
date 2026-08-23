# 项目执行清单

## Phase 0：归档、清零与计划落盘

- [x] 创建旧项目归档分支。
- [x] 提交当前已跟踪修改和研究 PDF。
- [x] 创建归档标签。
- [x] 创建 orphan `main`。
- [x] 删除旧实现和本地运行资产。
- [x] 恢复深度研究 Markdown 与 PDF。
- [x] 保存新 Project Plan。
- [x] 创建 README、`.gitignore` 和 `.env.example`。
- [x] 验证归档可恢复、主分支内容和敏感文件边界。
- [x] 创建新主分支根提交。

## Phase 1：用户需求与黄金评测集

- [x] 设计用户访谈提纲。
- [x] 完成 3 个 Luna 代理用户面板（共 6 个 Persona）。
- [x] 收集并复核 15 条公式推导 Prompt。
- [x] 收集并复核 15 条函数可视化 Prompt。
- [x] 定义黄金集数据格式和评分规范。
- [x] 完成 Phase 1 内部开发门禁报告。
- [ ] 在未来条件允许时补充真实用户市场验证。

## Phase 2：Manim 引擎选型

- [x] 固定 ManimCE 0.20.1 与 ManimGL v1.7.2 候选版本。
- [x] 建立 6 个跨引擎测试场景。
- [x] ManimCE 完成 12/12；ManimGL 首场景两次失败后按用户决定淘汰。
- [x] 汇总稳定性、速度、视觉、分段和部署评分。
- [x] 选择 ManimCE 并锁定镜像 digest 与运行依赖版本。

## Phase 3：工程骨架与领域契约

- [x] 初始化 Web、API、Runner、契约和测试包。
- [x] 定义核心领域对象和版本规则。
- [x] 建立单一契约源及同步校验。
- [x] 建立数据库迁移和基础 CI。

## Phase 4：可信渲染内核

- [x] 固化 Phase 4 规格、接口、48 次验收矩阵和 agent 文件所有权。
- [x] 编写并确认父级接口与失败分类红灯测试。
- [x] 建立 12 个可信参考 Scene。
- [x] 实现预览与终渲档位。
- [x] 生成日志、缩略图和元数据。
- [x] 实现失败分类和缓存键。
- [x] 完成黑盒、失败注入、重复性和性能测试。
- [x] 完成 36 次 preview 与 12 次 final 的真实渲染门禁。

## Phase 5：隔离沙箱与异步任务

- [x] 固化 Phase 5 规格、STRIDE 威胁模型、状态机和 agent 文件所有权。
- [x] 固化 schema 1.1、lease 接口、失败枚举和 Alembic 0002 迁移。
- [x] 编写父级接口与安全红灯测试。
- [x] Agent A：实现 API Job 生命周期。
- [x] Agent B：实现 Redis signal、Runner 租约与恢复。
- [x] Agent C：实现一次性无网络 Docker 沙箱。
- [x] Agent D：实现黑盒攻击、故障注入和性能统计。
- [x] 父 agent 完成接口集成、代码审查和 Required/Critical 修复。
- [x] 完成真实 Redis 重启、幂等和恢复门禁。
- [x] 完成真实 Docker 资源、取消、逃逸和残留容器门禁。
- [x] 保存 Phase 5 验收报告并确认 Phase 0–4 无回归。

## Phase 6：DeepSeek ContentPlan 生成

- [x] 固化规格、威胁模型、评分规则和 agent 文件所有权。
- [x] 固化 ContentPlan 1.1、生成接口、错误分类和 0003 迁移。
- [x] 编写并确认父级失败测试。
- [x] Agent A：实现 DeepSeek Provider、有限重试和用量元数据。
- [x] Agent B：实现业务语义校验、歧义和不支持策略。
- [x] Agent C：实现确定性 Prompt 模板和请求构造。
- [x] Agent D：实现黄金集评测、失败注入、重复性和统计。
- [x] 父 agent 完成 API、持久化、审查与结果合并。
- [x] 完成真实 API smoke 与 30 条黄金集 95/90/95 门禁。
- [x] 保存 Phase 6 验收报告并确认 Phase 0–5 无回归。

## Phase 7：完整 Python 生成、校验与修复

- [x] 父 agent 固化规格、威胁模型、状态机、共享契约、迁移和失败测试。
- [x] Agent A：完整 Python 生成 Prompt、参考 Scene 注入和响应解析。
- [x] Agent B：AST、import、调用、属性和 API 白名单安全校验。
- [x] Agent C：编译预检、Scene 结构校验、错误分类和日志脱敏。
- [x] Agent D：两次修复链、修复 Prompt 和按类别自动降级。
- [x] Agent E：黑盒攻击集、失败注入、重复性、质量和性能统计。
- [x] 父 agent 完成 API、持久化和 Phase 5/6 集成。
- [x] 通过首次 75%、修复后 90%、安全 100%、数学 90%、视觉 80% 门禁。
- [x] 保存 Phase 7 验收报告并确认 Phase 0–6 无回归。

## Phase 8：Web 工作台、账号与版本系统

- [x] 固化 Phase 8 规格、STRIDE 威胁模型、schema 1.4 和 0005 迁移。
- [x] Agent A：管理员账号、Argon2id、Session、首次改密和限流。
- [x] Agent B：Project CRUD 与 Prompt/ContentPlan 不可变版本历史。
- [x] Agent C：SSE 重连、任务恢复与鉴权 Artifact 交付。
- [x] 父 agent 完成第一批审查和 Phase 5–7 中间集成。
- [x] Agent D：登录、首次改密、全局布局和设计系统。
- [x] Agent E：三栏工作台和完整生成/渲染流程。
- [x] Agent F：双用户黑盒安全、故障注入和浏览器验收计划。
- [x] 父 agent 完成最终代码集成、安全修复和 Phase 8 状态报告。
- [x] 在项目内 Playwright/Chrome 隔离环境完成真实双用户浏览器验收。
- [x] 清理 Phase 2 历史 Ruff 基线并通过全仓 Ruff 门禁。

## Phase 9：质量诊断与回归

- [x] 父 agent 固化 Phase 9 规格、威胁模型、schema 1.5、0006 和 RED 测试。
- [x] Terra A：时间轴、目标时长与 ContentPlan 一致性诊断。
- [x] Terra B：确定性视觉诊断与脱敏证据。
- [x] Terra C：QualityReport、版本追踪、分页与 owner 隔离。
- [x] 父 agent 完成第一批审查、集成和中间门禁。
- [x] Terra D：两次自动修复与降级决策。
- [x] Terra E：30 条黄金集、失败注入和离线 60 条终态门禁。
- [x] Terra F：质量诊断 Web UI、响应式与可访问性。
- [x] 运行 30 条真实黄金任务、60 次 Preview/Final 回归。
- [x] 完成自动修复、重复签名熔断和降级验证。
