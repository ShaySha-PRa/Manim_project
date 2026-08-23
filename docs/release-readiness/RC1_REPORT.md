# v0.1.0-rc1 Release Readiness Report

## 1. 结论

**GO（代码与本地发布门禁通过；是否创建 `v0.1.0-rc1` tag 仍由用户决定）**

本候选以如下产品目标为基准：用户用自然语言描述科学或技术内容，系统自动完成理解、必要计算、动画设计、安全编译、渲染、质量验证和视频交付。内部仍保留两条受约束、可审计的产品路径，而不是一个可任意生成可执行代码的 live Agent：

```text
教学：Prompt → ContentPlan → 确定性 Storyboard/Compiler → CodeVersion
科研：Prompt → IntentSpec → 白名单工具 → AnimationIR 2.0 → 确定性 Compiler
两者 → Docker Sandbox → QualityReport → Artifact/MP4
```

教学默认路径已不再让模型生成自由 Manim Python。模型只填写严格 ContentPlan；公式和函数由受限表达式编译器与确定性 Storyboard 生成，未知表达式失败关闭。真实 production 浏览器已完成教学与科研视频生成、Preview/Final、质量诊断、刷新恢复和 MP4 下载。

本结论只覆盖本地 RC1 发布准备，不包含已取消的 Phase 10 或任何外部用户试用。未创建 tag。

候选分支为 `release/rc1-readiness`。由于已跟踪报告无法在自身内容中嵌入其最终 Git object SHA，最终 SHA 由报告提交后执行的 `git rev-parse HEAD` 写入 `/tmp/manim-rc1-final/evidence/final-candidate.txt`，并在交付消息中给出；所有最终门禁均在该 SHA 上执行。

## 2. 主要修改

### 教学理解与动画实现

- `content_plans/prompts/builder.py`：向真实 Provider 提供严格完整的 ContentPlan 示例，保留受众、语言、目标时长、全部公式步骤、视觉意图和假设。
- `code_generation/math_expression.py`：新增受限数学表达式编译器，只接受登记变量、常量、算术和函数；不使用 `eval`、lambda 或动态 import。
- `code_generation/ir_compiler.py`：公式逐步变换、函数坐标轴/曲线/关键特征、显式有限时间线、长文本安全字号和有界高亮；不再截断步骤或用默认曲线替代未知表达式。
- `code_generation/service.py`：教学公式/函数默认走 ContentPlan → Storyboard → Compiler；自由 Python Provider 只保留显式 legacy 兼容入口，production 默认不可达。
- `code_generation/repair/` 与 prompt builder：修复策略与提示词改为配合结构化、确定性生成边界。
- `IrStateChangeKind.INDICATE` 及生成契约：支持可审计的教学高亮操作。

### 科研表达与质量闭环

- `agent/intent_resolver.py`：显式 Fourier 最大谐波数不能被 Provider 静默缩小；非法范围要求确认。
- `compiler/manim.py`：Gibbs 局部视图保持在画面安全区，并用连续进度表达逼近过程，消除长静态和越界错误。
- `render-panel.tsx`：只在 Job 进入终态后读取 QualityReport，消除 queued/running 阶段的无效 404 轮询。

### 产品呈现

- Web 标题、metadata、入口说明和导航文案统一为“科学与技术动画工作台”。
- 教学 ContentPlan 不再标为“旧入口”；交付面板明确教学与科研两条内部路径都会生成可审计 CodeVersion。
- `README.md`、`AGENTS.md`：记录统一产品目标、两条受约束生成路径、安全边界和本地运行方式。

### 回归测试

- 新增受限表达式、公式全步骤、函数关键特征、目标时长、长中文布局、Fourier 参数忠实度和 production 默认不调用自由 Python Provider 的测试。
- 更新 Phase 8 黑盒架构断言：恶意自由 Python Provider 在默认教学路径中调用次数必须为 0，结果必须是 `compiled_ir` 且 `provider_model=null`。
- 更新 Web 边界测试，覆盖新产品定位和终态后质量读取。

## 3. 问题与根因

### 教学模型输出不稳定且视频内容弱

旧路径让 LLM 直接生成完整 Scene Python，真实 held-out 中出现 schema、语法、lambda、遗漏 import、时长不足和纯文本占位。根因不是提示词措辞，而是模型同时承担理解、动画规划和可执行实现。现改为 LLM 只填写 ContentPlan，执行逻辑由受限表达式编译器与确定性 Storyboard/Compiler 完成；不支持的技术内容结构化失败，不伪造公式或曲线。

### 教学长中文说明触发质量拒绝

真实浏览器圆面积请求首次 Preview 的 `object_out_of_bounds` 为 35 个边缘像素。按文本长度确定字号后降至 11；帧级定位确认只在第 25 秒 `Indicate` 默认放大 20% 时触边。最终高亮缩放限制为 1.05，Preview/Final 均成功，实际时长 30.4/30.0 秒。保留 `object_overlap` warning，质量为 92/100，不隐藏降级原因。

### Fourier 请求丢失显式参数并出现静态/越界

Provider 曾把用户要求的 31 个谐波缩小为 5，且局部 zoom 将对象裁出画面，随后出现长静态诊断。服务端现以后校验保留用户显式最大项数；编译器调整局部视图并增加连续逼近进度。真实 Preview/Final 质量 100，浏览器生成、播放、下载和刷新恢复通过。

### pytest 曾被误判为挂起

历史长无输出来自真实 Docker P0 测试，具有明确 60 秒 deadline 并会正常退出。本轮另一次聚焦测试停在 `TestClient.__enter__`，faulthandler 证明是工具网络沙箱禁止本地 socketpair；在正常本机测试环境同组 25 项 1.27 秒通过。没有增加无界 timeout、删除/skip/xfail 测试或降低断言。

### Web production build 和本机 rewrite

原 `next/font/google` 在构建期联网，已改为系统字体栈。验收中还确认 Next.js rewrite 在 build 时固化：漏传 `MANIM_WORKBENCH_API_URL` 的构建会指向默认 8000；以 8012 重新 build 后 production 浏览器通过。正式本地命令必须在 build 时提供 API URL，或保持项目推荐的同源默认服务端口。

## 4. 验证证据

| 门禁 | 结果 | 证据 |
| --- | --- | --- |
| Ruff / diff | pass | `uv run ruff check .`; `git diff --check` |
| 契约同步 | pass，schema 1.10，无漂移 | `scripts/generate_contracts.py --check` |
| Web | lint、typecheck、production build pass；无 Google Fonts | command output / execution log |
| pytest 最终 Run 1 | 613 passed，正常退出 | `/tmp/manim-pytest-final-1.log` |
| pytest 最终 Run 2 | 613 passed，正常退出 | `/tmp/manim-pytest-final-2.log` |
| migration | 空库升级到 `0008_asset_versions (head)` | `/tmp/manim-rc1-migration.PL6aIG/empty.db` |
| 教学 API E2E | ContentPlan/compiled_ir/Preview/Final/Artifact/Quality pass | `/tmp/manim-rc1-final/teaching/evidence/teaching.json` |
| 教学浏览器 E2E | Preview/Final、质量 92、下载 1,412,898 bytes、刷新恢复 | `/tmp/manim-rc1-final/teaching/evidence/browser-teaching.json` |
| 教学 held-out | 2/2 首次与最终渲染；数学 5/5、视觉 4/5；攻击 8/8 阻断 | `/tmp/rc1-teaching-deterministic-report-final.jsonl` |
| 科研无资产 Docker | Lorenz Preview/Final 均 30.0 秒，无 error 诊断 | `/tmp/manim-rc1-duration-quality/report.json` |
| 科研浏览器 E2E | Fourier Preview/Final 质量 100、下载、刷新恢复 | `/tmp/manim-rc1-final/evidence/browser.json` |
| CSV AssetVersion | 真实 CSV、工具 input/output hash、Preview/Final 30.0 秒 | `/tmp/manim-rc1-duration-quality/report.json` |
| 安全停止 | missing CSV=`asset_required`；unknown paper=`needs_confirmation`；0 CodeVersion/RenderJob | `/tmp/manim-rc1-final/safety/evidence/safety.json` |
| DeepSeek held-out | 2 教学 + 2 科研 + 2 资产 + 2 缺资料；模型、template、assumptions、工具、IR hash、repair、最终状态均脱敏记录 | `/tmp/rc1-scientific-provider-heldout.json` 及教学报告 |
| 恢复 | API/Runner 中断后唯一终态，无部分 Artifact | `/tmp/manim-rc1-final/recovery/evidence/recovery.json` |
| 候选 SHA 与清理 | 最终 SHA、分支、工作区、容器/进程检查 | `/tmp/manim-rc1-final/evidence/final-candidate.txt` |

最终环境：Python 3.10.20、Node 22.23.1、npm 10.9.8、Docker 29.1.3、Chromium 151.0.7922.34；Sandbox ManimCE 使用项目固定版本。`uv.lock` SHA-256 为 `b06b5bf8282180ab0e384f65c7da9f9c448e4fff11686559df148506bfd70d17`，`package-lock.json` SHA-256 为 `1edd3fe6e59cc96b4fe601b5ba60aa6caa6318b315daa6ed57fc4d1392f02d85`。

## 5. 已知限制与残余风险

1. RC1 是受约束能力集，不等于可以忠实生成任意科学主题。未登记的公式、工具、论文或资产必须停止并请求确认。
2. 教学圆面积实测保留 `object_overlap` warning（92/100）；可交付但不是视觉满分，后续可改进布局而不放宽质量门禁。
3. 浏览器 console 捕获一条通用 404 文本，但 Playwright 的 HTTP response 记录为 0 个失败响应，独立网络捕获也未发现页面请求 404；作为低风险浏览器噪声保留。
4. 本地默认 `auth_disabled=true`，所以 `/login` 按设计重定向工作台，不存在 production 登录/退出表单。Cookie、CSRF、session 恢复和跨 owner 隔离由完整自动化套件覆盖。
5. API 停机跨过 sandbox 完成点时可能由 lease 恢复触发第二次 attempt；最终状态和 Artifact 唯一，但可能增加计算成本。

## 6. Git 状态

- 分支：`release/rc1-readiness`
- 基线：`cd2823d fix: enforce render duration and quality publication`
- 最终候选 SHA：见 `/tmp/manim-rc1-final/evidence/final-candidate.txt` 与交付消息
- 工作区：最终门禁后 clean
- 推送：将按用户已授权的“提交并推送”执行
- tag：未创建；`v0.1.0-rc1` 仍需用户单独确认
- Phase 10 / 外部试用：已取消，不执行、不恢复

## 7. 下一步

代码可合并到 `main`。合并与推送完成后保持本地 RC1，不自动创建 tag，也不开始外部试用。若用户后续明确要求发布 tag，再创建并推送 `v0.1.0-rc1`。
