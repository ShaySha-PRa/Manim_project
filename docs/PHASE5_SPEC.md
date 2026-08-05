# Phase 5 规格：隔离沙箱与异步任务

日期：2026-08-04  
状态：父 agent 已冻结，供并行实现使用

## 目标

在任何模型生成的 Python 进入渲染流程之前，建立可恢复、可取消、幂等且最小权限的异步任务链路：

```text
API → SQLite transaction → Redis Job ID signal → Host Runner
    → one-shot untrusted render container → artifacts → API/SQLite
```

SQLite 是唯一状态真相源。Redis 只保存可丢失、可由 SQLite 重建的 Job UUID 唤醒信号，不保存源码、租约、令牌、产物、错误详情或用户数据。

## 已确认技术栈

- FastAPI `0.139.2`
- SQLAlchemy `2.0.51`
- Alembic `1.18.5`
- SQLite WAL
- Redis server `8.2.1-alpine`
- redis-py `8.0.1`
- Docker Engine / Docker Desktop via WSL Host Runner
- ManimCE `0.20.1` immutable image digest inherited from Phase 4
- Shared contract schema `1.1`

## 范围

### Phase 5 包含

- RenderJob 提交、读取和取消 API。
- 内部 Runner claim、heartbeat、start、complete 和 fail API。
- Redis Job ID signal queue。
- SQLite lease、heartbeat、attempt、cancellation 和 optimistic state version。
- Host Runner 领取、恢复、取消和幂等协调。
- 一次性无网络 Docker 沙箱。
- 超时、CPU、内存、PID、临时空间和输出大小限制。
- 重启、重复提交、过期租约和取消竞争测试。
- 黑盒安全攻击与失败注入。

### Phase 5 不包含

- 用户登录、会话和跨用户产品权限；属于 Phase 8。
- DeepSeek 或任何模型调用；属于 Phase 6–7。
- AST/import 白名单；属于 Phase 7。
- Web 工作台和 SSE；属于 Phase 8。
- 公网部署和多主数据库。

Phase 5 API 必须绑定私有/本地网络，并使用内部服务令牌保护所有 RenderJob 路由。在 Phase 8 用户认证完成前，不得作为公网用户 API 发布。

## 状态机

```text
queued ──claim──> claimed ──start──> running ──complete──> succeeded
   │                  │                 │
   └──cancel──────────┴──cancel─────────┴──cancel──────> cancelled
                      │                 │
                      └──expired────────┴──retry───────> queued
                                        └──fail────────> failed
```

- 终态：`succeeded`、`failed`、`cancelled`，不可离开。
- `claimed` 表示已取得租约，不增加同义 `leased` 状态。
- claim 原子设置 `lease_owner`、随机 256-bit `lease_token`、`lease_expires_at`，并递增 `attempt_count` 与 `state_version`。
- claim 响应同时携带内部执行所需的 `scene_class`、`source_code` 和 `source_sha256`；Runner 不得直连 SQLite，并在落盘前复核源码哈希。
- heartbeat、start、complete、fail 必须同时匹配 Job ID、非过期 lease token 和允许的当前状态。
- 过期 lease 最多重排至 `queued` 三次；达到最大尝试次数后转 `failed/runner_lost`。
- queued 取消立即进入 `cancelled`；claimed/running 取消写入 `cancellation_requested_at`，Runner 必须终止容器并确认 cancelled。
- cancellation 已请求后不得接受 success completion。
- 旧 Runner 的过期 lease token 永远不能更新新租约。

## API 接口

所有路由统一前缀 `/api/v1`，错误格式固定为：

```json
{"error":{"code":"MACHINE_CODE","message":"safe public message"}}
```

### 作业路由

- `POST /render-jobs`：提交；相同 idempotency key 返回同一 Job。
- `GET /render-jobs/{job_id}`：读取状态。
- `POST /render-jobs/{job_id}/cancel`：幂等请求取消。

### Runner 内部路由

- `POST /internal/render-jobs/{job_id}/claim`
- `POST /internal/render-jobs/{job_id}/heartbeat`
- `POST /internal/render-jobs/{job_id}/start`
- `POST /internal/render-jobs/{job_id}/complete`
- `POST /internal/render-jobs/{job_id}/fail`
- `POST /internal/render-jobs/{job_id}/cancelled`
- `GET /internal/render-jobs/recoverable?limit=...`

内部路由通过常量时间比较验证 `X-Internal-Token`。令牌只来自环境变量，不进入 Redis、数据库、日志、Docker 参数或子容器环境。

## Redis 信号契约

- key namespace：`manim-workbench:phase5:render-jobs`。
- payload 必须恰好是 ASCII UUID，例如 `018f...-....`。
- 禁止 JSON、源码、路径、owner ID、项目 ID、lease token 和错误详情。
- 提交顺序：先提交 SQLite，再发送 Redis 信号。
- Redis 发送失败不回滚已提交 Job；恢复扫描会重新发出 queued Job ID。
- 重复 Job ID 信号允许存在；数据库 claim 是唯一去重边界。
- Redis 不可用时使用有界退避，不得无限阻塞 API 或 Runner。

## Docker 沙箱策略

每个 attempt 使用唯一且由 Job UUID 派生的容器名。命令必须包含：

- `--rm`
- `--network none`
- `--read-only`
- `--cap-drop ALL`
- `--security-opt no-new-privileges`
- Docker 默认 seccomp profile，不得使用 `seccomp=unconfined`
- 非 root UID/GID
- `--pids-limit 64`
- `--cpus 1.0`
- `--memory 1g` 与 `--memory-swap 1g`
- `--tmpfs /tmp:rw,noexec,nosuid,nodev,size=256m`
- `--tmpfs /home/manim:rw,noexec,nosuid,nodev,size=64m`
- source file 单文件只读挂载到 `/input/scene.py`
- attempt output 单目录读写挂载到 `/output`
- `HOME=/home/manim`
- `--pull never`

禁止：

- `--privileged`
- host/pid/ipc namespace
- Docker socket
- 项目根、用户目录、数据库、Redis、令牌或任意密钥挂载
- 用户控制的镜像、容器名、挂载目标、entrypoint 或附加参数
- shell 字符串执行；必须使用 argv

Host Runner 必须使用 container ID file 或确定性名称在 timeout/cancel 后执行 stop/kill/remove，并验证容器不存在。输出发布前拒绝符号链接、路径逃逸、非预期文件和超过限制的总大小。

## 失败分类

使用封闭枚举，不提供 `internal_error`：

- `render_failed`
- `sandbox_timeout`
- `sandbox_oom`
- `sandbox_pid_limit`
- `sandbox_output_limit`
- `sandbox_security_violation`
- `artifact_publish_failed`
- `lease_expired`
- `runner_lost`

未知异常向上抛出并由父级审查补充模型，不得静默归入模糊类别。

## 威胁边界

详细 STRIDE 分析见 `docs/PHASE5_THREAT_MODEL.md`。安全原则：

- API 不能访问 Docker socket。
- Runner 是唯一 Docker 控制者。
- 渲染容器不信任源码、输入路径、输出内容或日志。
- 模型代码即使通过未来 AST 检查仍视为恶意。
- prompt 和 system prompt 不是安全边界。
- 完成记录只有在产物验证和原子发布后才能写入。

## Agent 文件所有权

### 父 agent 独占

- `docs/PHASE5_*.md`
- `tasks/plan.md`、`tasks/todo.md`
- `packages/contracts/**`
- `migrations/**`
- `infra/compose.yaml`
- `pyproject.toml`、`uv.lock`
- `apps/api/src/manim_workbench_api/main.py`
- `apps/api/src/manim_workbench_api/phase5_runtime.py`
- `apps/runner/src/manim_workbench_runner/__main__.py`
- `apps/runner/src/manim_workbench_runner/phase5_runtime.py`
- `tests/phase5/parent/**`
- `tests/phase5/integration/**`

### Terra Agent A

- `apps/api/src/manim_workbench_api/jobs/**`
- `tests/phase5/api/**`

### Terra Agent B

- `apps/runner/src/manim_workbench_runner/queue/**`
- `tests/phase5/runner/**`

### Terra Agent C

- `apps/runner/src/manim_workbench_runner/sandbox/**`
- `tests/phase5/sandbox/unit/**`

### Terra Agent D

- `tests/phase5/security/**`
- `benchmarks/phase5/**`

任何 agent 发现共享契约不足时只能报告父 agent，不得越界修改。

## 测试策略

- Small：状态转换、令牌、signal codec、command builder、输出路径。
- Medium：SQLite 真实迁移、FastAPI dependency overrides、fake Redis、fake Docker runner。
- Large：真实 Redis、真实 Docker、服务重启、攻击容器。
- 测试不得依赖公网。
- 真实 Docker 安全测试串行运行，避免并行容器互相污染。

## 门禁

- Phase 0–4 全量测试无回归。
- 相同 idempotency key 的并发提交只创建一个 Job。
- 重复 Redis signal 只允许一个有效 lease。
- 旧 lease token 无法 heartbeat/start/complete/fail。
- Runner、API 或 Redis 重启后 queued/expired Job 可恢复。
- 无限循环、fork bomb、OOM、磁盘填满和网络访问被限制并分类。
- 路径穿越与 symlink 无法读取或发布沙箱外内容。
- timeout/cancel 后无残留容器。
- Redis key/value 审计只出现命名空间和 Job UUID。
- API/Redis 容器没有 Docker socket；只有 Host Runner 调用 Docker。
- 完整 Phase 5 测试、Ruff、契约同步和迁移升降级通过。

## 命令

```bash
uv run pytest -s -q tests/phase5
uv run pytest -s -q
uv run ruff check apps/api apps/runner packages/contracts tests/phase5 benchmarks/phase5
uv run python scripts/generate_contracts.py
uv run python scripts/generate_contracts.py --check
docker compose -f infra/compose.yaml config
sg docker -c 'docker ps'
```

## 官方依据

- Docker run reference: https://docs.docker.com/reference/cli/docker/container/run/
- Docker seccomp: https://docs.docker.com/engine/security/seccomp/
- Redis job queue: https://redis.io/docs/latest/develop/use-cases/job-queue/redis-py/
- redis-py production usage: https://redis.io/docs/latest/develop/clients/redis-py/produsage/
- FastAPI dependencies: https://fastapi.tiangolo.com/tutorial/dependencies/
- FastAPI test dependency overrides: https://fastapi.tiangolo.com/advanced/testing-dependencies/
