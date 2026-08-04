# Phase 3 验收报告：工程骨架与领域契约

日期：2026-08-04

## 结论

Phase 3 门禁通过。项目已建立可运行的 Next.js Web、FastAPI API、Host Runner、SQLite/Alembic、Redis 开发服务和共享契约包，但没有提前加入业务界面、模型调用、任务队列或 Docker 控制。

仓库已从 Windows 挂载盘迁到 WSL 原生目录：

```text
/home/developer/projects/Manim_project
```

原生文件系统消除了 DrvFS 上复现的 npm 目录清理和 Next.js 类型检查子进程输出问题。

## 已交付边界

- `apps/web`：Next.js `16.3.0` App Router 工程状态页。
- `apps/api`：FastAPI `0.139.2`，提供 `GET /api/v1/health`。
- `apps/runner`：Phase 3 安全空入口，明确报告 `docker_access=false`。
- `packages/contracts`：Pydantic `2.13.4` 单一契约源及 JSON Schema、TypeScript 生成产物。
- `migrations`：Alembic `1.18.5` 首个 SQLite 迁移。
- `infra/compose.yaml`：只声明 Redis 开发服务，不实现 Phase 5 队列。
- `.github/workflows/ci.yml`：Python 与 Web 两条基础 CI 门禁。

## 契约结果

八个根类型均已固化：

- `User`
- `Project`
- `PromptVersion`
- `ContentPlanVersion`
- `CodeVersion`
- `RenderJob`
- `Artifact`
- `GenerationAttempt`

除身份根 `User` 外的所有项目记录都包含非空 `owner_id`。`PromptVersion`、`ContentPlanVersion` 和 `CodeVersion` 在 Pydantic 层冻结，在 SQLite 层由触发器阻止 `UPDATE` 与 `DELETE`。

生成产物拒绝未声明属性，不生成 `any`、`unknown`、字符串索引签名或 `other` 枚举。

## 数据库结果

- 创建八张领域表及 `alembic_version`。
- SQLite 连接启用 `journal_mode=WAL` 与 `foreign_keys=ON`。
- 三张版本表具有 `(project_id, version)` 唯一约束。
- Manim 引擎字段固定为 `manimce` / `0.20.1`。
- 迁移可从临时空数据库升级到 `head`。

## 验证结果

| 门禁 | 结果 |
|---|---|
| Phase 3 Python 测试 | 15 passed |
| 完整 Python 测试套件 | 31 passed |
| Python lint | passed |
| Web ESLint | passed |
| TypeScript | passed |
| Next.js production build | passed |
| npm production audit | 0 vulnerabilities |
| Redis Compose 配置校验 | passed |
| 本地页面 HTTP 验证 | `GET /` 200，标题与 Schema 1.0 内容正确 |

## 已知边界

- FastAPI `TestClient` 当前产生一条来自依赖组合的弃用警告，不影响测试结果；后续升级到 Starlette 推荐的新测试客户端时处理。
- Redis 尚未承载消息；SQLite 尚未开放 CRUD API。
- Runner 不读取内部令牌、不访问 Docker，也不执行渲染。
- Web 页面明确显示工程骨架状态，不模拟尚未实现的产品能力。
- 当前 Codex 任务仍绑定旧 `/mnt/i` 工作区，浏览器控制器拒绝连接；迁移后已完成 HTTP 实机响应验证，重新从 WSL 新目录打开任务后补做截图、控制台和可访问性树检查。

## Phase 4 入口

Phase 4 可以在不改变现有领域边界的前提下，加入 12 个可信参考 Scene、预览/终渲档位、产物元数据、失败分类与缓存键。
