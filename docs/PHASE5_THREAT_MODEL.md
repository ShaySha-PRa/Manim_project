# Phase 5 STRIDE 威胁模型

日期：2026-08-04

## 资产

- 内部服务令牌与未来模型 API 密钥。
- SQLite 中的用户、项目、源码版本、Job 和产物记录。
- WSL 项目目录、用户主目录和 Docker daemon。
- Host CPU、内存、PID、磁盘和网络。
- 渲染产物的完整性和 Job 状态机正确性。

## 信任边界

```text
client/untrusted request
        │
        ▼
API container ── SQLite
        │
        ▼
Redis (Job UUID only)
        │
        ▼
Host Runner ── Docker daemon
        │
        ▼
untrusted one-shot render container
        │
        ▼
staging output ── validation ── artifact store
```

## STRIDE

| 边界 | 威胁 | 主要控制 | 验收证据 |
|---|---|---|---|
| Client → API | Spoofing | Phase 5 内部令牌、常量时间比较、私网绑定 | 缺失/错误 token 均为 401 |
| Client → API | Tampering | Pydantic strict contracts、UUID/enum/长度限制、参数化 SQL | 非法状态、额外字段和注入输入被拒绝 |
| API/Runner | Repudiation | Job state/version、attempt、UTC 时间与失败码落库 | 每次状态变化可追踪 |
| Redis | Information disclosure | value 仅 UUID；禁止源码、路径、owner 和 token | 全 key/value 黑盒审计 |
| API/Redis | Denial of service | 输入上限、连接/命令 timeout、有界 retry | Redis 停止时 API 快速失败且 DB Job 可恢复 |
| Runner claim | Elevation/tampering | 原子 claim、随机 lease token、expiry、state_version | 并发 claim 只有一个成功，旧 token 被拒 |
| Runner → Docker | Elevation | Runner 独占 socket；argv；固定镜像/entrypoint/flags | API 无 socket，攻击参数不能改变命令 |
| Render container | Information disclosure | network none、最小挂载、无 secrets/env、只读 root | 读取项目/home/socket/metadata 均失败 |
| Render container | Denial of service | CPU/memory/PID/tmpfs/output/time limits | loop/fork/OOM/disk 攻击受限 |
| Render container | Elevation | non-root、cap-drop ALL、NNP、默认 seccomp | capability/privilege 探测失败 |
| Output → Host | Tampering | staging、拒绝 symlink/path escape、文件 allowlist、hash | 恶意 symlink/额外文件不发布 |
| Cancel/complete | Race | cancellation_requested_at + lease token + conditional update | cancel 后 completion 被拒，容器清理 |
| Restart | Availability | SQLite truth、queued/expired recovery scan、duplicate-safe signal | API/Redis/Runner 重启恢复 |

## 明确不作为安全边界

- Prompt 或 system prompt。
- 未来 Phase 7 AST 校验。
- Redis 持久化。
- Docker 容器名。
- 文件扩展名。
- 用户声明“代码是安全的”。

## 剩余风险

- Docker daemon 本身拥有宿主高权限，因此 Runner 必须保持单用途、最小输入面并运行在受控 WSL 用户下。
- Docker 默认 seccomp 是兼容性与安全性的折中；若黑盒测试证明不足，后续以版本化自定义 profile 加固。
- Phase 5 尚无最终用户认证；所有 Job 路由在 Phase 8 前只能部署在私网并使用内部令牌。
- 单机 SQLite 不提供多主容灾；Phase 5 目标是本机/小范围试用的可恢复性。

