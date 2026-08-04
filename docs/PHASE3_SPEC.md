# Phase 3 规格：工程骨架与领域契约

## 1. 目标

建立可运行、可迁移、可持续验证的单仓库骨架，并把后续阶段共同依赖的领域对象固定为机器可检查的契约。本阶段不提供业务工作台，不执行模型生成或 Manim 渲染。

## 2. 范围

### 包含

- Next.js App Router Web 空壳。
- FastAPI API，当前只暴露版本化健康检查。
- Host Runner 可执行空壳；它不连接 Docker，也不领取任务。
- SQLite 数据库与 Alembic 首个迁移，连接时启用 WAL 和外键。
- Redis 开发服务声明；队列协议留到 Phase 5。
- ManimCE `0.20.1` 渲染镜像沿用 Phase 2 已验证镜像。
- Pydantic 领域模型作为单一契约源，确定性生成 JSON Schema 与 TypeScript 类型。
- 契约、迁移、API、Runner 和 Web 的自动化检查及基础 CI。

### 不包含

- 登录、项目 CRUD、Prompt 编辑器或任何业务界面。
- Redis 队列、任务领取、状态机编排或 Docker socket 访问。
- ContentPlan 模型调用、Python 代码生成、修复和实际渲染。
- 为未来需求预留任意字典、`Any`、`other` 枚举或自由参数字段。

## 3. 架构边界

```text
apps/web                 只负责浏览器界面
apps/api                 同步 HTTP 边界与数据库访问
apps/runner              宿主机进程边界，Phase 3 不执行任务
packages/contracts       唯一领域契约源及生成产物
migrations               SQLite 模式演进
benchmarks/phase2        已选 ManimCE 渲染器镜像
tests                    跨包门禁
```

- SQLite 是持久状态真相源；Redis 未来只传递 Job ID。
- API 永远不控制 Docker；只有 Host Runner 可在 Phase 5 获得该能力。
- `User` 是身份根对象；其余七个项目领域对象必须包含 `owner_id`。
- `PromptVersion`、`ContentPlanVersion` 和 `CodeVersion` 是追加型记录。修改内容必须新增版本，数据库层拒绝更新或删除已有版本行。

## 4. 契约规则

核心根类型：

- `User`
- `Project`
- `PromptVersion`
- `ContentPlanVersion`
- `CodeVersion`
- `RenderJob`
- `Artifact`
- `GenerationAttempt`

共同规则：

- 所有对象拒绝未声明字段，并在 Pydantic 层冻结。
- ID 使用 UUID；时间使用带时区的 ISO 8601 `datetime`。
- 字符串均有明确长度或格式约束；枚举只列出首版支持值。
- JSON 字段使用 `snake_case`，与计划中的 `schema_version` 等名称一致。
- 版本号从 1 开始；版本 1 不允许父版本，后续版本必须指向父版本。
- `ContentPlanVersion.schema_version` 固定为 `1.0`，并明确包含标题、受众、语言、目标时长、显式假设和至少一个场景。
- 每个场景明确包含教学目标、至少一个公式步骤、视觉意图和旁白占位。

## 5. API 与运行入口

- `GET /api/v1/health`
- 成功响应：`{"status":"ok","service":"api","contract_schema_version":"1.0"}`
- Runner 提供 `python -m manim_workbench_runner`，输出自身状态与契约版本后正常退出。
- Web 只显示工程骨架状态和下一阶段说明，不模拟业务功能。

## 6. 数据库规则

- 默认数据库 URL：`sqlite:///./data/manim_workbench.db`。
- 每个 SQLite 连接启用 `PRAGMA foreign_keys=ON` 和 `PRAGMA journal_mode=WAL`。
- 首个迁移创建八张领域表及 `alembic_version`。
- 除 `users` 外，所有领域表都有非空 `owner_id` 与外键。
- 三张版本表具有 `(project_id, version)` 唯一约束。
- 版本表通过数据库触发器阻止 `UPDATE` 和 `DELETE`，避免绕过 ORM。

## 7. 单一契约源

`packages/contracts/src/manim_workbench_contracts/models.py` 是唯一可编辑契约源。生成脚本输出：

- `packages/contracts/generated/contracts.schema.json`
- `packages/contracts/generated/contracts.ts`

CI 重新生成到内存并与已提交文件逐字节比较；任何漂移都会失败。TypeScript 生成器只接受受支持的 JSON Schema 子集，遇到未知或无约束结构直接报错。

## 8. 验收标准

- Python 契约测试证明必填字段、枚举、额外字段拒绝、版本链和冻结行为。
- 生成同步测试证明 JSON Schema 与 TypeScript 产物无漂移，且不存在 `Any`、`unknown`、`other` 或任意附加属性。
- Alembic 可在临时 SQLite 数据库从空库升级到 `head`，表、外键、唯一约束和版本不可变触发器可检查。
- API 健康检查与 Runner 冒烟测试通过。
- Web 的 lint、类型检查与生产构建通过。
- GitHub Actions 在 Python 3.10 与 Node 22 上运行相同门禁。

## 9. 实施顺序

1. 先提交规格和失败测试。
2. 实现共享契约及确定性生成器。
3. 实现数据库、迁移、API 和 Runner。
4. 建立 Web 空壳和 CI。
5. 运行全部门禁，记录版本、命令、结果和剩余风险。

## 10. 依赖基线

- Python `>=3.10`，与当前 WSL Python 3.10 及 FastAPI 支持范围一致。
- Node.js 22，满足 Next.js 当前最低要求并使用现有 LTS 运行时。
- FastAPI `0.139.2`、Pydantic `2.13.4`、SQLAlchemy `2.0.51`、Alembic `1.18.5`。
- Next.js `16.3.0`；WSL 挂载盘构建由脚本把源码暂存到 Linux 临时文件系统，绕开子进程输出丢失问题。
- 其余 Web 依赖由 lockfile 固定精确解析版本。

## 11. 官方依据

- FastAPI: https://fastapi.tiangolo.com/
- Pydantic JSON Schema: https://docs.pydantic.dev/latest/concepts/json_schema/
- SQLAlchemy SQLite: https://docs.sqlalchemy.org/en/20/dialects/sqlite.html
- Alembic tutorial: https://alembic.sqlalchemy.org/en/latest/tutorial.html
- Next.js installation: https://nextjs.org/docs/app/getting-started/installation
