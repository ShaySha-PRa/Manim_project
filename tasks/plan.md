# Implementation Plan: Phase 5 隔离沙箱与异步任务

## Overview

以 Phase 4 的可信同步渲染内核为基准，增加 SQLite 权威状态、Redis UUID 唤醒信号、Host Runner 租约协调和一次性无网络 Docker 沙箱。父 agent 先冻结所有共享边界，再由四个 Terra agent 在互斥目录并行实现，最后由父 agent 串行集成和运行真实攻击门禁。

## Architecture Decisions

- SQLite 是唯一状态真相源；Redis 信号可丢失、可重复、可重建。
- 沿用 `claimed` 表示有效租约，lease token 防止旧 Runner 写回。
- API 通过依赖注入隔离数据库、signal publisher 和内部认证，便于真实/测试实现替换。
- Sandbox command builder 与 Docker executor 分离；所有安全参数先做纯函数测试。
- 真实 Docker 攻击测试只由 Agent D/父 agent 串行执行。
- 父 agent 独占共享契约、迁移、依赖和入口文件。

## Dependency Graph

```text
父规格/威胁模型/状态机/迁移/红灯测试
       ├── A API Job lifecycle
       ├── B Redis + Runner lease/recovery
       ├── C Docker sandbox policy/executor
       └── D black-box security/failure tests
                    ↓
              父级接口集成
                    ↓
       fake-boundary tests → real Redis → real Docker
                    ↓
             restart/idempotency/security gates
```

## Task List

### Slice 0：父级冻结

- [x] 核对 Phase 4 工作区并保护未提交修改。
- [x] 核对 Docker、Redis、FastAPI 官方模式。
- [x] 固化 `docs/PHASE5_SPEC.md` 和 STRIDE 威胁模型。
- [x] 固化 schema 1.1、状态机、lease 和失败枚举。
- [x] 创建 Alembic `0002_phase5` 迁移。
- [x] 编写父级接口与安全红灯测试。
- [ ] 生成契约并确认父级基础测试通过、实现边界测试红灯。

### Slice 1：四 agent 并行

- [ ] Terra A：API Job 生命周期与 API 测试。
- [ ] Terra B：Redis signal、Runner 租约/恢复与测试。
- [ ] Terra C：Sandbox policy/executor 与单元测试。
- [ ] Terra D：黑盒安全、失败注入、恢复与 benchmark。

### Slice 2：父级集成

- [ ] 五轴审查四个 agent，拒绝越界修改。
- [ ] 集成 API router、依赖注入和内部令牌。
- [ ] 集成 Runner queue、API client、sandbox 和 Phase 4 renderer。
- [ ] 更新 Compose，只让 Host Runner 接触 Docker。
- [ ] 修复 Required/Critical findings。

### Slice 3：门禁

- [ ] 运行 Phase 5 与全仓测试、Ruff、契约和迁移检查。
- [ ] 运行真实 Redis 提交/重复/恢复/重启测试。
- [ ] 运行真实 Docker loop/fork/OOM/disk/network/path/symlink 测试。
- [ ] 验证 timeout/cancel 无残留容器。
- [ ] 验证 Phase 4 可信渲染无回归。
- [ ] 保存 `docs/PHASE5_STATUS.md` 并更新总计划/todo。

## Checkpoints

- Slice 0：共享基础绿灯；A/B/C 模块缺失导致边界测试精确红灯。
- Slice 1：agent 文件范围完全互斥，自己的测试通过。
- Slice 2：fake DB/Redis/Docker 端到端状态机通过。
- Slice 3：真实安全和恢复门禁通过后才能声明完成。

## Risks and Mitigations

| 风险 | 影响 | 缓解 |
|---|---|---|
| Redis 与 SQLite 双写 | 丢失/重复任务 | DB 先提交；Redis 仅 signal；恢复扫描 |
| 取消与完成竞争 | 错误成功状态 | lease token + conditional state update |
| Docker 参数被输入污染 | 宿主提权 | 固定 argv、固定镜像、派生名称、无附加参数 |
| 攻击测试损害宿主 | 资源耗尽 | 先静态/假执行测试，再串行小限制实测 |
| 四 agent 改共享文件 | 合并冲突 | 硬性文件所有权，越界只报告 |
| Phase 4 未提交改动混入 | 难审查 | 保留并按路径审查，不重写、不清理 |

## Official Sources

- https://docs.docker.com/reference/cli/docker/container/run/
- https://docs.docker.com/engine/security/seccomp/
- https://redis.io/docs/latest/develop/use-cases/job-queue/redis-py/
- https://redis.io/docs/latest/develop/clients/redis-py/produsage/
- https://fastapi.tiangolo.com/tutorial/dependencies/
- https://fastapi.tiangolo.com/advanced/testing-dependencies/
