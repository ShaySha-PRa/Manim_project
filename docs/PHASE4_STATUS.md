# Phase 4 验收报告：可信渲染内核

日期：2026-08-04

## 结论

Phase 4 门禁通过。项目已具备面向仓库内可信 Scene 的同步渲染内核、两档固定渲染配置、确定性缓存、原子产物、视频探测、结构化失败，以及可恢复的 48 次真实渲染验收流程。

本阶段没有提前接入 API、Redis、异步任务或不可信模型代码；这些安全与编排边界仍属于 Phase 5。

## 分工与交付边界

- 父 agent：规格、公共接口、失败测试、渲染内核、档位、元数据、缓存键、错误分类、代码审查、合并与最终验收。
- Terra Agent A：仅交付 `reference_scenes/formula/` 下 6 个公式推导 Scene。
- Terra Agent B：仅交付 `reference_scenes/functions/` 下 6 个函数可视化 Scene。
- Terra Agent C：仅交付 `tests/phase4/blackbox/` 与 `benchmarks/phase4/` 下的验收工具。

三个子 agent 的可写范围互不重叠，公共渲染契约由父 agent 独占维护。

## 渲染内核

- preview：`854×480`、`15 fps`、Manim `-ql`、超时 `60 s`。
- final：`1920×1080`、`60 fps`、Manim `-qh`、超时 `300 s`。
- renderer 固定为 Cairo，随机种子固定为 `0`。
- 镜像固定为 `manimcommunity/manim@sha256:f18f53f2e4eaf2ea41713437d34363fb3f5cc6008b03fd798676ac0359396c3b`。
- 每次成功发布 `video.mp4`、`thumbnail.jpg`、`render.log` 和 `metadata.json`。
- 缓存键覆盖源码哈希、Scene 类名、完整档位参数、镜像 digest 和渲染契约版本。
- 失败分类覆盖请求校验、Docker、渲染超时、Manim、视频探测、视频校验、缩略图和产物发布；不提供模糊的 `internal_error` 兜底。

固定镜像不包含独立的 `ffprobe`/`ffmpeg` 命令，但包含 PyAV `16.1.0` 及其链接的 FFmpeg 库。因此视频流探测和抽帧均在同一固定容器内通过 PyAV 完成，镜像身份和运行环境没有漂移。

## 参考 Scene

公式推导：

- 一元一次方程
- 配方法
- 二次公式
- 勾股关系
- 等比数列求和
- 差商到导数

函数可视化：

- 正弦参数变换
- 抛物线参数变化
- 三次函数移动切线
- 黎曼和面积
- 二次函数关键特征
- 指数函数与切线比较

## 自动验证

| 门禁 | 结果 |
|---|---|
| Phase 4 聚焦测试 | `37 passed` |
| 完整 Python 测试套件 | `68 passed` |
| Phase 4 Ruff | passed |
| 生成契约同步检查 | passed |
| 补丁空白与冲突标记检查 | passed |

完整测试仍有一条来自 Starlette/httpx 依赖组合的既有弃用警告，不影响结果。

## 真实渲染验收

有效矩阵为 12 Scene ×（3 preview + 1 final），共 48 次，全部禁用产品缓存和 Manim partial cache。

| 指标 | 结果 |
|---|---|
| 有效渲染 | `48/48` |
| 成功率 | `100%` |
| preview 样本数 | `36` |
| preview 中位耗时 | `5.5711725 s` |
| 视频流属性重复性 | passed |
| 视频哈希差异 | `0` |
| 最终门禁 | passed |

验收日志采用追加式 JSONL。首轮 48 次成功后，人工检查 12 张 final 缩略图发现指数比较 Scene 的标签和底部读数拥挤；修复后仅追加 3 次 preview 与 1 次 final 重试。原始证据未覆盖，因此日志共 52 条物理记录，汇总器按每个验收键的最后一条记录计算 48 条有效结果。

人工复核全部 12 张 final 缩略图后未发现剩余的文字重叠、裁切或不可读问题。

## 固定环境

- Python `3.14.3`
- ManimCE `0.20.1`
- PyAV `16.1.0`
- libavcodec `62.11.100`
- libavformat `62.3.100`
- pdfTeX `1.40.28` / TeX Live `2025`
- Noto Sans、Noto Serif、Noto Mono

验收期间宿主 UTC 墙钟出现过跳变；耗时统计使用单调的 `time.perf_counter()`，因此性能数据不受影响。

## 证据位置

- 规格：`docs/PHASE4_SPEC.md`
- 验收脚本：`benchmarks/phase4/run_acceptance.py`
- 汇总器：`benchmarks/phase4/summarize.py`
- 本地运行证据：`runtime/phase4-acceptance/`

`runtime/` 被 Git 忽略，只作为本机可复核证据，不进入源码提交。

## Phase 5 入口

Phase 5 可以在不改变同步渲染契约的前提下，为它增加 API、Redis、Host Runner 领取任务、一次性无网络容器、资源限制、取消、幂等和恢复机制。可信 Scene 内核继续作为沙箱与异步链路的确定性基准。
