# Manim 科学与技术动画工作台

项目目标是构建由 LLM 驱动的科学与技术动画创作系统：用户只需描述想展示的内容，系统负责受约束的意图理解与规划、白名单计算、动画设计、确定性编译、隔离渲染和视频交付。当前仓库是这一产品的本地开发与验收工作台，不是生产部署方案。

仓库里有两条路径，实现和口径都不要混：

```
教学  Prompt → ContentPlan → SceneStoryboard → Compiler → CodeVersion → Preview/Final
科研  一句话 → IntentSpec → 白名单 Tools → AnimationIR 2.0 → Compiler → 同一套 Preview
```

两条路径中 LLM 都只产生受契约约束的语义数据，不是自由代码执行器。教学路径由 LLM 填写 `ContentPlan`，公式和函数场景再转换为 `SceneStoryboard` 并确定性编译；不支持的函数表达式或缺少 Storyboard 的几何/3D 请求会结构化失败，不生成纯文字占位视频。科研路径（Animation Agent V2）只允许 LLM 填写 `IntentSpec`；模型不得写自由 Scene、lambda 或 Scene 里的 `np.exp`，数字来自 ToolRun，编译器 lowering 预计算数组。所有编译结果仍须通过 AST/API allowlist 和 Docker render sandbox。

一句话 Intent：有 `DEEPSEEK_API_KEY` 时 LLM 只填 `IntentSpec` JSON（围栏、Manim Python、非法 JSON 一律拒绝）；没有密钥则走 `resolve_intent_catalog` 关键词目录。CSV 无正文返回 `asset_required`。论文/PDF 只有命中封闭 Lotka–Volterra 目录且系数齐全才跑 `ode_compare`，否则 `needs_confirmation`，不补公式。

工作台默认不登录：`GET /auth/session` 签发 `dev@local.test` 会话，Cookie / CSRF / owner 隔离仍生效。`/login` 会跳到 `/workbench`。需要 Phase 8 登录链路时设 `MANIM_WORKBENCH_AUTH_DISABLED=false`。

契约版本以健康检查为准，当前是 `1.10`。

![工作台](docs/assets/workbench-demo.png)

教学路径 Final 示例：[MP4](docs/assets/formula-derivation-demo.mp4)

## 布局

```
浏览器
  │ Cookie / SSE，同源 /api
  ▼
Next.js  :3000  ── rewrite /api → FastAPI :8000
  ▼
FastAPI  :8000 ── SQLite
  ├── 教学：ContentPlan / CodeVersion
  ├── 科研：Intent → Tools → AnimationIR → Compiler
  └── Redis 队列
          ▲
    Python Runner
          │
    Compute 沙箱（白名单工具） / Render 沙箱（禁网 Docker）
```

| 路径 | 内容 |
| --- | --- |
| `apps/api` | FastAPI：鉴权、两条生成路径、质量报告 |
| `apps/runner` | Redis 队列、租约、Docker 渲染、产物与诊断 |
| `apps/web` | Next.js 工作台 |
| `packages/contracts` | Python / TypeScript 契约；改源文件后跑生成脚本，不要手改 `generated/` |
| `migrations/versions` | Alembic |
| `reference_scenes` | Manim 参考 Scene |
| `tests/` | `phase*`、`agent`、`ir`、`web` |
| `eval/`、`benchmarks/` | gold set、benchmark、阶段验收证据 |

## 环境

在 WSL 原生路径跑，例如 `/home/<user>/projects/Manim_project`。不要从 `/mnt/c` 装 Node 或跑构建。

- Windows + WSL2（Ubuntu 或兼容发行版）
- Python 3.10、[uv](https://docs.astral.sh/uv/)
- Node.js ≥ 22
- Docker Desktop，打开 WSL2 Integration
- Git、curl、openssl

## 安装

```bash
git clone git@github.com:ShaySha-PRa/Manim_project.git
cd Manim_project
uv sync --frozen
npm ci --ignore-scripts
cp .env.example .env
openssl rand -hex 32
```

把生成的 token 写进 `.env` 的 `MANIM_WORKBENCH_INTERNAL_TOKEN`，并填 `DEEPSEEK_API_KEY`（没有密钥时科研路径仍可用关键词目录）。其余字段与 `.env.example` 一致即可：

```
MANIM_WORKBENCH_DATABASE_URL=sqlite:///./data/manim_workbench.db
MANIM_WORKBENCH_REDIS_URL=redis://127.0.0.1:6379/0
MANIM_WORKBENCH_API_URL=http://127.0.0.1:8000
MANIM_WORKBENCH_COOKIE_SECURE=false
```

不要设置 `NEXT_PUBLIC_API_URL`。浏览器必须打 Web 同源的 `/api`，由 `apps/web/next.config.ts` rewrite 到本机 API，否则会话 Cookie 会跨源丢失。Runner 只接受本机 API 地址，不要填外部网卡 IP。

```bash
docker compose -f infra/compose.yaml up -d redis
uv run --env-file .env alembic upgrade head
```

不要提交 `.env`、密钥、`data/`、`runtime/`。

## 启动

三个进程，都在仓库根目录。

API：

```bash
uv run --env-file .env uvicorn manim_workbench_api.main:app --host 0.0.0.0 --port 8000
```

Runner（看到 `idle` / `recovery_complete` 即在等任务）：

```bash
uv run --env-file .env python -m manim_workbench_runner run
```

Web（默认 :3000）：

```bash
npm run dev:web
```

Windows 浏览器若 `localhost` 进不了 WSL，用 `hostname -I` 的第一段 IP，并把它加进 `.env`：

```
MANIM_WORKBENCH_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,http://<WSL_IP>:3000
NEXT_ALLOWED_DEV_ORIGINS=localhost,127.0.0.1,<WSL_IP>
```

然后：

```bash
cd apps/web
NEXT_ALLOWED_DEV_ORIGINS=<WSL_IP> ../../node_modules/.bin/next dev --hostname 0.0.0.0
```

WSL 重启后 IP 可能变。API 仍听 `0.0.0.0:8000`，`MANIM_WORKBENCH_API_URL` 仍用 `http://127.0.0.1:8000`。

| 用途 | 地址 |
| --- | --- |
| 工作台 | http://127.0.0.1:3000/workbench |
| OpenAPI | http://127.0.0.1:8000/docs |
| 健康检查 | http://127.0.0.1:8000/api/v1/health |

```bash
curl -fsS http://127.0.0.1:8000/api/v1/health
curl -fsS -o /dev/null -w 'web=%{http_code}\n' http://127.0.0.1:3000/workbench
```

健康检查应返回 `{"status":"ok","service":"api","contract_schema_version":"1.10"}`。`GET /` 返回 `Not Found` 是正常的。

强制走登录 API 时才需要：

```bash
uv run --env-file .env python scripts/create_user.py your@email.com
```

## 开发时怎么走两条路径

科研：创建项目 → 一句话 Prompt →「生成科研动画」。未匹配切片会 `needs_confirmation`，不会出片。匹配后走 ToolRun → AnimationIR → Compiler → Preview。

无密钥时关键词目录会命中：波包/干涉、傅里叶/Gibbs/方波、Lorenz/洛伦兹、PID/阶跃响应、CSV/temperature/异常、Frenet/切向量/螺旋。

```
展示二维波动方程中两个波包碰撞后的干涉过程
```

教学：展开 ContentPlan → 提交 Prompt → 生成 CodeVersion（浏览器只读）→ Preview → 可选 Final。质量报告看时长、静止帧、乱码、越界、关键对象缺失。

```
讲解如何从一般式 y=ax^2+bx+c 推导二次函数的顶点坐标公式。
通过配方法逐步变形，说明顶点横坐标为什么是 -b/(2a)，并使用 y=2x^2-4x+1 验证结果。
```

P1：`asset_versions` 追加写、TIFA 风格 critic（可选 provider 只填 `CriticJudgement` JSON）、IR 修复最多一轮且不写 Scene Python。P2：`register_simulator` 进程内插件（模型不能点名新 op）、同一 IR 的 `renderer_hint=web` JSON backend（不是 Blender）、tool npz / 可选 IR compile 缓存。OpenFOAM / FEniCS 和外部用户研究不在本仓库范围。

## 测试

```bash
uv run python scripts/generate_contracts.py --check
uv run ruff check .
uv run pytest -s -q
npm run lint && npm run typecheck && npm run build
```

阶段与 Agent 门禁：

```bash
uv run python scripts/phase8_acceptance.py
uv run python scripts/phase9_acceptance.py
uv run python scripts/agent_p0_acceptance.py          # 可加 --skip-render
uv run python scripts/agent_p1_acceptance.py
uv run python scripts/agent_p2_acceptance.py
```

改契约源文件后：`uv run python scripts/generate_contracts.py`。改 schema 后：`uv run alembic upgrade head`。

## 常见问题

**按钮没反应 / CORS。** 浏览器 origin 必须在 `MANIM_WORKBENCH_ALLOWED_ORIGINS` 里；WSL IP 变了要改 `.env` 并重启 Web。

**打到 :8000 根路径 Not Found。** UI 在 Web `:3000/workbench`，API 用 `/docs` 或 `/api/v1/health`。

**无法恢复会话。** 未设置 `NEXT_PUBLIC_API_URL`，页面和 `/api` 同源；API 在 :8000 跑着。

**Runner：`Phase 5 API must use a private/local HTTP endpoint`。** `MANIM_WORKBENCH_API_URL=http://127.0.0.1:8000`。

**Preview 提交失败。** 科研路径需要 Intent 已匹配且 Compiler 产出；教学路径需要已确认的 ContentPlan 和 CodeVersion。看 API / Runner 终端第一条错误，不要只看前端提示。

## 约定

- Conventional Commit：`feat:` / `fix:` / `test:` / `docs:` / `chore:`
- Python 3.10、四空格、Ruff 100 列；TS 两空格
- 不提交 `.env`、密钥、数据库、渲染视频、沙箱产物
- 推送前跑相关 lint / typecheck / 测试
