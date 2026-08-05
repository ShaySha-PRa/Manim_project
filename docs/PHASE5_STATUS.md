# Phase 5 验收状态：隔离沙箱与异步任务

日期：2026-08-04
结论：通过

## 已交付

- FastAPI RenderJob 提交、读取、幂等、取消与内部 lease 生命周期。
- SQLite 权威状态、乐观版本、三次 attempt、过期恢复和 Alembic `0002_phase5`。
- Redis 只传规范 Job UUID；丢失和重复信号均由 SQLite claim/recovery 收敛。
- Host Runner HTTP 生命周期适配、启动恢复、有界退避、运行中 heartbeat/cancel。
- 一次性 Docker 沙箱：固定 digest、无网络、只读根、非 root、drop capabilities、
  `no-new-privileges`、CPU/内存/PID/tmpfs/输出/时长限制。
- 固定 Python wrapper 只发布 video、thumbnail、render log、metadata 四类产物。
- Compose API/Redis 边界；两者均不挂载 Docker socket，只有 Host Runner 控制 Docker。

## 父级审查修复

- claim 响应内嵌 `scene_class/source_code/source_sha256`，Runner 不读取 SQLite。
- Redis 发布只吞明确的可恢复连接故障；未知异常向上抛出。
- 同一 idempotency key 的不同请求返回 409；终态清除 lease 凭证。
- cancel/complete、旧 lease、新 lease 与过期恢复均使用条件更新。
- 沙箱运行期间持续 heartbeat；取消、超时和输出超限均执行 stop/kill/rm/inspect。
- 绑定输出目录增加运行中大小监控，发布前再做 allowlist、symlink 和总大小校验。
- 将 BLAS/OMP/MKL/NumExpr/BLIS 线程固定为 1，在保持 PID 64 上限时兼容 Pango。
- Alembic 与 API 统一读取 `MANIM_WORKBENCH_DATABASE_URL`。
- Starlette TestClient 按官方要求增加 `httpx2==2.7.0`。

## 验收证据

- Phase 5 测试：`100 passed`；最终全仓：`168 passed`。
- 变更范围 Ruff、生成契约同步、迁移升级/降级、Compose config：通过。
- Web：ESLint、TypeScript、Next.js production build：通过。
- 真实 Redis：唯一 key 为 `manim-workbench:phase5:render-jobs`；value 全为规范 UUID；
  重启后 AOF 恢复 2 条重复信号，精确测试 key 已清理。
- 真实攻击：9/9 通过；JSONL 共 10 条（fork 修订后断点续跑 1 条）；
  中位 `0.528701 s`，最大 `5.191844 s`，无未缓解输出、无残留容器。
- 真实产品 smoke：`LinearEquationDerivation` 成功发布四产物；视频 63,036 bytes，
  缩略图 7,107 bytes；运行中取消在第 2 次 probe 生效，无容器和产物残留。
- Compose API 镜像构建成功；容器 health 返回 schema `1.1`；PID 1 为
  UID/GID `10001:10001`；API/Redis 挂载目标都只有 `/data`。

本地证据位于（已由 `.gitignore` 排除）：

- `runtime/phase5-attacks/runs-v2.jsonl`
- `runtime/phase5-attacks/summary-v2.json`
- `runtime/phase5-smoke/artifacts/`

## 环境说明

宿主端口 8000 已被无关容器 `ita-project-api-1` 占用，因此未启动带宿主端口映射的
常驻 Compose API；验收改用不发布宿主端口的临时 Compose API，容器内部健康检查通过。
未停止或修改该无关容器。验收临时容器与网络已移除，named volumes 保留。

## Phase 6 入口条件

Phase 5 已满足。Phase 6 可接入 DeepSeek ContentPlan，但模型生成的 Python 在 Phase 7
AST/import 校验完成前仍不得进入本沙箱。
