# Manim 数学动画工作台：分阶段开发计划

## 总体原则

项目按依赖关系划分为 Phase 0–10。每个 Phase 必须通过验收门禁后才能进入下一阶段，不按固定日期强行推进。

主链路：

```text
项目重置
→ 用户与语料验证
→ Manim 引擎选型
→ 工程与契约
→ 可信渲染内核
→ 安全沙箱和异步任务
→ ContentPlan 生成
→ 完整 Python 生成与修复
→ Web 工作台
→ 质量回环
→ 小范围试用
```

首版仅支持公式推导和函数可视化，使用 `deepseek-v4-flash`，用户只能查看、不能在线编辑生成的 Python。

## Phase 0：归档、清零与计划落盘

### 目标

安全保留旧项目历史，建立完全干净的新主分支。

### 工作内容

- 将当前代码、未提交修改和研究 PDF 保存到 `archive/phase0-1-2026-08-04`。
- 创建归档标签 `archive-phase0-1-2026-08-04`。
- 创建无父提交的 orphan `main`。
- 删除旧代码、数据库、虚拟环境、Node 缓存、渲染产物、本地 Manim clone 和旧 `.env`。
- 保留深度研究 Markdown 和 PDF。
- 将本计划保存到 `docs/PROJECT_PLAN.md`，任务清单保存到 `tasks/todo.md`。
- 新建 README、`.gitignore`、`.env.example` 和基础开发约定。
- 建立新的根提交。

### 门禁

- 归档分支可以正常切换和恢复。
- `main` 不包含任何旧实现。
- 新主分支工作区干净。
- 研究资料和新计划可读。
- Git 中不存在密钥、数据库和生成产物。

## Phase 1：用户需求与黄金评测集

### 目标

先用独立代理用户确认问题、任务表达和质量标准，避免由父 agent 单方面臆测需求。

### 工作内容

- 由 3 个相互独立的 Luna 子 agent 模拟目标用户访谈，共覆盖至少 6 个教师、创作者和内容编辑 Persona。
- 收集至少 30 条代理用户原始 Prompt：15 条公式推导、15 条函数可视化。
- 记录用户期望的成片、可编辑程度、等待时间和失败容忍度。
- 为每条 Prompt 定义教学目标、必须出现的公式和对象、禁止错误、预期场景结构、时长范围和人工评分标准。
- 将黄金集保存为版本化测试资产。
- 所有代理访谈必须标记为 `synthetic_interview`；它们可满足内部开发门禁，但不作为真实市场验证结论。

### 门禁

- 3 个代理用户面板均认可“Prompt → 教学规划确认 → 渲染”的工作流，并明确可接受等待时间、编辑点和失败边界。
- 30 条黄金任务全部有可执行评分规则。
- 明确首版不支持的需求并形成拒绝或降级策略。
- 父 agent 完成数学正确性复核；门禁报告明确记录“外部真实用户验证待完成”。

## Phase 2：ManimCE 与 ManimGL 选型

### 目标

用实验决定渲染引擎，不沿用旧项目假设。

### 测试场景

- 公式逐步变形
- 导数推导
- 单函数绘图
- 参数动态变化
- 切线动画
- 曲线下面积

每个场景在两种引擎中无头渲染两次。

### 评分

- 无头稳定性：40%
- 低清渲染速度：20%
- 代码生成首次成功率：15%
- 公式和函数视觉能力：10%
- 分段与缓存能力：10%
- 镜像及部署复杂度：5%

### 选择规则

- 12 次渲染未全部成功的引擎直接淘汰。
- 总分高者胜出。
- 分差不超过 10 分时选择 Manim Community。
- 选定后固定精确引擎、FFmpeg、LaTeX 和字体版本。

参考：[ManimCE Docker](https://docs.manim.community/en/stable/installation/docker.html)、[ManimCE Sections](https://docs.manim.community/en/stable/guides/configuration.html)、[3b1b/manim](https://github.com/3b1b/manim)。

### 门禁

- 选型报告包含命令、输入场景、耗时、结果和失败记录。
- 在 Windows + WSL2 + Docker Desktop 上可重复。
- 选定引擎版本正式写入技术契约。

### 实施结果（2026-08-04）

- 选择 Manim Community `0.20.1`，官方镜像 12/12 次无头渲染成功。
- ManimGL `v1.7.2` 在首个场景两次无头启动失败后由项目发起人决定淘汰。
- 精确镜像 digest、Python、PyAV/FFmpeg 库、LaTeX 和字体版本见 `docs/PHASE2_STATUS.md` 与 ADR-001。

## Phase 3：工程骨架与领域契约

### 目标

建立新项目的稳定边界，不开发业务界面。

### 工程组成

- Next.js Web
- FastAPI API
- Host Runner
- Redis
- SQLite WAL
- 渲染器镜像
- 共享契约包
- 黄金集与测试包

### 核心类型

- `User`
- `Project`
- `PromptVersion`
- `ContentPlanVersion`
- `CodeVersion`
- `RenderJob`
- `Artifact`
- `GenerationAttempt`

`ContentPlanVersion` 至少包含 `schema_version`、标题、受众、语言、目标时长、显式假设、场景教学目标、公式步骤、视觉意图和旁白占位。

所有版本对象不可原地覆盖；用户修改必须创建新版本。所有项目数据带 `owner_id`。

### 门禁

- JSON Schema、Pydantic 和 TypeScript 类型由单一契约源生成或验证同步。
- 数据库迁移、契约测试和基础 CI 通过。
- 不存在 `other` 类型或任意无约束参数逃生字段。

### 实施结果（2026-08-04）

- 建立 Next.js `16.3.0`、FastAPI `0.139.2` 和 Host Runner 单仓库骨架。
- 以 Pydantic `2.13.4` 为单一契约源生成 JSON Schema 与 TypeScript。
- 建立 SQLite WAL、Alembic 首个迁移和数据库级版本不可变触发器。
- 建立 Redis 开发服务声明与 Python/Web 基线 CI；没有提前实现队列或渲染。
- 仓库迁移到 `/home/developer/projects/Manim_project`，避免 WSL 挂载盘文件语义问题。

## Phase 4：可信渲染内核

### 目标

先使用人工编写的可信 Scene 打通完整渲染流程。

### 工作内容

- 建立 12 个参考 Scene，每类 6 个。
- 实现低清预览与高清终渲档位。
- 生成 MP4、缩略图、日志和元数据。
- 记录引擎版本、源码哈希、渲染时长、视频时长和产物哈希。
- 检测空视频、零帧、异常时长、缺少产物和 FFmpeg 失败。
- 实现相同代码和渲染参数的缓存键。

### 门禁

- 12 个参考 Scene 连续三轮全部成功。
- 输出结果可重复。
- 低清预览中位数目标不超过 60 秒。
- 失败均被分类，不返回模糊的内部错误。

### 实施结果（2026-08-04）

- 建立 6 个公式推导和 6 个函数可视化参考 Scene，并由父 agent 完成全部终渲缩略图审查。
- Host Runner 提供固定 preview/final 档位、确定性缓存键、原子产物发布、结构化元数据和封闭失败分类。
- 固定 ManimCE `0.20.1` 镜像；同一镜像内使用 PyAV 探测视频流并提取缩略图，不依赖镜像中不存在的 `ffprobe`/`ffmpeg` 可执行文件。
- Phase 4 聚焦测试 `37 passed`，完整 Python 套件 `68 passed`；Ruff 与契约同步检查通过。
- 48 个有效真实渲染全部成功，视频流属性可重复，preview 中位耗时 `5.571 s`；为修复一处视觉排版追加 4 条重试记录，保留了完整的追加式证据。

## Phase 5：隔离沙箱与异步任务

### 目标

在接入模型代码前建立不可信代码执行边界。

### 架构

- Web、API、Redis 使用 Docker Compose。
- Runner 在 WSL 用户环境运行，是唯一允许控制 Docker 的组件。
- API 容器不挂载 Docker socket。
- Redis 只传递 Job ID；SQLite 是状态真相源。
- Runner 使用内部令牌领取任务和提交结果。

### 一次性渲染容器约束

- 禁止网络。
- 非 root 用户、只读根文件系统。
- 删除全部 capabilities，启用 `no-new-privileges`。
- 限制 CPU、内存、PID、磁盘和总时长。
- 源码只读挂载，仅输出目录可写。
- 不挂载项目目录、用户目录、Docker socket 或密钥。
- 取消或超时后终止整个容器。

### 门禁

- 无限循环、fork bomb、OOM、磁盘填满和网络访问均被限制。
- 路径穿越无法读取工作区或宿主机文件。
- Runner、API、Redis 重启后任务状态可恢复。
- 重复提交不会重复渲染同一幂等任务。

### 实施结果（2026-08-04）

- 完成 SQLite 权威状态、Redis UUID 信号、Host Runner lease/recovery 与内部 HTTP 接口。
- 完成固定镜像、无网络、非 root、只读根、资源受限的一次性 Docker 沙箱。
- 真实 Redis 重启与信号审计通过；9 类真实攻击全部受控且零残留容器。
- 真实参考 Scene 通过 Phase 5 adapter 发布四类产物，运行中取消链路通过。
- Compose API 以 UID/GID 10001 运行，API/Redis 均无 Docker socket；完整证据见
  `docs/PHASE5_STATUS.md`。

## Phase 6：DeepSeek ContentPlan 生成

### 目标

把用户 Prompt 转换成可确认的教学规划。

### 模型配置

- 模型：`deepseek-v4-flash`
- Base URL：`https://api.deepseek.com`
- ContentPlan 使用非思考模式和 JSON Output。
- API Key 只存在于 API 环境变量。
- 模型输出必须经过本地 JSON Schema 和业务语义校验。
- 空响应、截断或非法 JSON 最多自动重试一次。

DeepSeek JSON Output 保证合法 JSON，但不等同于严格 Schema，因此不能省略本地验证。参考：[DeepSeek JSON Output](https://api-docs.deepseek.com/guides/json_mode/)。

### 歧义处理

- 受众、时长、推导风格和关键假设必须显式展示。
- 系统不得静默猜测关键数学意图。
- 不支持的内容返回结构化限制说明。

### 门禁

- 黄金集 Schema 合法率不低于 95%。
- 业务语义通过率不低于 90%。
- 数学公式解析成功率不低于 95%。
- 所有失败都有明确重试或用户修正路径。

### 当前状态

Phase 6 已于 2026-08-04 通过。最终 30 条真实 DeepSeek 黄金集为 Schema 30/30、
业务语义 29/30、公式解析 30/30、可行动结果 30/30；三次重复结构稳定率为 16.7%，
作为 Phase 7 的非阻断风险持续跟踪。详见 `docs/PHASE6_STATUS.md`。

## Phase 7：完整 Python 生成、校验与修复

### 目标

根据确认后的 ContentPlan 生成完整 Manim Scene。

### 模型输出契约

```json
{
  "scene_class": "GeneratedScene",
  "code": "...",
  "assumptions": []
}
```

### 代码策略

- 使用 `deepseek-v4-flash` 思考模式。
- Prompt 注入固定引擎版本、参考 Scene、允许 API 和失败案例。
- 每次只允许一个 Scene 子类。
- 顶层只允许白名单 import、常量和类定义。
- import 仅允许选定 Manim 包、`math` 和受限 `numpy`。
- 禁止文件、网络、进程、动态导入、反射、dunder、`eval`、`exec`、`compile`、`open`。
- AST 校验通过后才可进入 Phase 5 沙箱。
- 编译或渲染失败时，使用分类后的精简日志修复，最多两次。
- 不向模型发送宿主机路径、密钥或完整内部日志。

### 门禁

- 首次渲染成功率不低于 75%。
- 两次修复后成功率不低于 90%。
- 安全攻击集拦截率 100%。
- 数学正确性不低于 4/5 的样例占比不低于 90%。
- 视觉清晰度不低于 4/5 的样例占比不低于 80%。

### 降级规则

- 某一类别连续两轮未达标，则该类别停止完整代码生成并进入确定性模板编译路线。
- 已达标类别继续使用完整代码生成。
- 安全门禁失败时全部代码生成暂停。

### 当前状态

Phase 7 已于 2026-08-05 通过。最终 30 条真实 DeepSeek + Docker 黄金集首次渲染
`27/30`、最终渲染 `28/30`、数学质量不低于 4 分 `28/30`、视觉质量不低于
4 分 `28/30`；8 个安全攻击全部在沙箱前拦截且无绕过。全仓 `356 passed`，
Ruff、契约同步、前端 lint/typecheck/build 和敏感信息审计均通过。详见
`docs/PHASE7_STATUS.md`。

## Phase 8：Web 工作台、账号与版本系统

### 目标

向真实用户提供完整但受控的创作体验。

### 界面

- 左栏：Prompt、受众、时长和生成入口。
- 中栏：可编辑 ContentPlan、公式步骤和显式假设。
- 右栏：视频、诊断、任务状态和版本历史。
- Python 位于高级只读面板，可查看和下载，不能修改执行。
- JSON 不作为普通用户入口。

### 账号

- 管理员 CLI 创建用户，不开放注册。
- Argon2id 密码哈希。
- HttpOnly、SameSite Cookie 会话。
- 首次登录强制修改初始密码。
- 所有资源按 owner 隔离。

### 公开接口

- 登录和退出。
- 项目 CRUD。
- ContentPlan 生成与版本保存。
- CodeVersion 生成与只读查询。
- 预览和终渲提交。
- Job 查询、取消和 SSE 进度。
- 鉴权后的 Artifact 预览与下载。

### 门禁

- 用户无需接触 JSON 或修改 Python 即可完成完整流程。
- 跨用户资源访问全部被拒绝。
- 页面刷新、浏览器关闭和服务重启后任务及版本仍存在。
- 失败消息能指出发生问题的管线阶段。

### 当前状态（2026-08-05）

Phase 8 的后端、Web 和安全实现已完成：schema `1.4`、Alembic `0005`、Argon2id
账号与服务端 Session、首次登录改密、项目和不可变版本、SSE 续传、鉴权 Artifact、
共享 API Client 与三栏工作台均已落地。独立双用户攻击集 `11/11` 通过，Phase 8/Web
定向测试 `67 passed`，全仓 `423 passed`，前端 lint/typecheck/build、契约同步、迁移
升降级、npm audit、pip-audit、生产代码敏感信息扫描均通过。

Phase 8 遗留门禁已于 2026-08-05 关闭：项目内 Playwright 1.62.1 / Chrome 151 完成真实
双用户浏览器流程、SSE `Last-Event-ID`、API 进程替换、视频交付、四断点和键盘验收；
Phase 2 的 212 条历史 Ruff 基线已清零，全仓 Ruff 与 428 个 Python 测试通过。浏览器门禁
同时发现并修复了重复刷新丢失 `job` 查询参数的问题。详见
`docs/PHASE8_BROWSER_ACCEPTANCE.md`。

## Phase 9：质量诊断、回归与自动降级

### 当前状态（2026-08-05）

Phase 9 已完成：schema `1.5`、Alembic `0006_phase9`、append-only QualityReport、稳定诊断、
目标时长贯穿、确定性视觉采样、两次修复预算、质量 Web UI 和 STRIDE 边界均已落地。
15 个公式和 15 个函数黄金任务均完成真实 Preview/Final，共 60 次终态渲染；全部为 90 秒，
Preview/Final 时间轴差为 0，严重视觉项为 0。全仓 519 个 Python 测试、真实双用户浏览器、
迁移升降级、前端构建和依赖安全门禁通过。详见 `docs/PHASE9_STATUS.md`。

### 目标

从“能生成视频”提升到“动画可用于教学”。

### 诊断能力

- 空白或近空白画面
- 文字和公式越界
- 明显重叠
- 字号过小
- 关键公式缺失
- 视频时长异常
- 对象未出现
- 动画顺序与 ContentPlan 不一致

### 版本追踪

- 模型 ID
- Prompt 版本
- ContentPlan Schema 版本
- 引擎和镜像版本
- AST 策略版本
- 修复次数
- 人工评分

暂不引入 VLM；先使用确定性规则和人工评测。

### 门禁

- 30 条黄金任务完整回归。
- 常见失败能够自动分类。
- 可自动修复的问题最多两次重试。
- 无法修复时保留日志、失败代码和用户可理解的建议。
- 模型或引擎升级不会静默降低黄金集指标。

## Phase 10：小范围试用与项目收敛

### 目标

验证真实使用价值，而不是继续扩充功能。

### 发布方式

- 在本机 Windows + WSL2 + Docker Desktop 运行。
- 通过 LAN 或 Tailscale 等私有网络向 5–10 位受邀用户开放。
- 不开放公共互联网注册。
- 开放前运行完整黄金集、安全集和权限测试。

### 观测指标

- Prompt 到首次预览时间
- 首次渲染成功率
- 修复后成功率
- 平均修复次数
- 用户修改 ContentPlan 的次数
- 数学正确性和视觉清晰度
- 用户完成任务比例
- 用户是否愿意继续使用或付费

### 试用结束后的决策

- 公式达标、函数不达标：只保留公式产品线。
- 函数达标、公式不达标：只保留函数产品线。
- 两类都达标：进入模板扩充和正式部署。
- 两类都不达标：停止扩功能，回到 ContentPlan、代码生成和模板策略。
- 未经新一轮规划，不进入几何、线代、语音、时间轴、协作、计费和公开注册。

### 门禁

- 至少 5 位用户独立完成真实任务。
- 不低于 Phase 7 的质量指标。
- 无高危沙箱或越权问题。
- 完成试用报告、已知问题、成本记录和下一版本建议。

## 全程质量规则

每个 Phase 都必须：

- 有自动测试和可重复手工验收。
- 保持主分支构建通过。
- 不提交密钥、数据库、模型输出或视频产物。
- 更新对应文档和任务状态。
- 使用小规模、可回滚提交。
- 不在门禁失败时通过扩功能掩盖核心问题。
