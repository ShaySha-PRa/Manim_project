# Phase 4 规格：可信渲染内核

## 1. 目标

使用人工编写、仓库内版本化的 12 个可信 ManimCE Scene，建立确定、可诊断、可重复的同步渲染内核。Phase 4 只验证渲染本身；异步任务、Redis 编排、不可信代码隔离和 Docker 安全限制留到 Phase 5。

## 2. 已确认假设

- 引擎唯一支持 Manim Community `0.20.1`，使用 ADR-001 固定的官方镜像 digest。
- 参考集包含 6 个公式推导 Scene 和 6 个函数可视化 Scene，每个文件只暴露一个可渲染 Scene 类。
- 48 次最终验收定义为：12 Scene × 3 次 preview = 36 次，另加 12 Scene × 1 次 final = 12 次。
- preview 的性能门禁以 36 次无缓存实测的中位数为准，目标不超过 60 秒。
- final 用于验证高清产物链路，不要求连续三轮；如果未来要求 final 也连续三轮，验收总数应改为 72 次并先更新本规格。

## 3. 范围与边界

### 包含

- 同步 Host Runner 渲染接口、两种固定档位和确定性缓存键。
- MP4、JPEG 缩略图、完整日志和 JSON 元数据四种产物。
- 用固定镜像内的 PyAV 16.1.0 及其链接的 FFmpeg 库检查视频并生成缩略图；该镜像不包含 `ffprobe`/`ffmpeg` CLI。
- 空文件、零帧、异常时长、缺少产物、Manim 失败、FFmpeg 失败、超时和 Docker 不可用的分类。
- 12 个参考 Scene，以及可重复执行的 48 次黑盒验收和性能汇总。

### 不包含

- API endpoint、数据库写入、Redis 队列、重试编排或 Web UI。
- 用户或模型生成代码；Phase 4 输入必须来自仓库内的参考 Scene 清单。
- 网络隔离、只读根文件系统、capability、PID/内存/CPU 配额；这些是 Phase 5 门禁。
- 对视频教学质量做 VLM 自动评分；本阶段只做确定性技术检查与父 agent 人工抽样。

## 4. 目录与所有权

```text
apps/runner/src/manim_workbench_runner/rendering/  父 agent：内核、接口、档位、缓存、错误、元数据
reference_scenes/formula/                         Agent A：6 个公式推导 Scene
reference_scenes/functions/                       Agent B：6 个函数可视化 Scene
tests/phase4/blackbox/                            Agent C：黑盒、失败注入、重复性测试
benchmarks/phase4/                                Agent C：48 次验收与性能统计脚本
tests/phase4/test_*.py                            父 agent：接口和单元级失败测试
docs/、tasks/                                     父 agent：规格、计划和状态
```

三个子 agent 不得编辑其所有权之外的文件。父 agent 在子 agent 工作期间不编辑上述三个子 agent 目录，只在结果返回后审查和必要修正。

## 5. 公共 Python 接口

`manim_workbench_runner.rendering` 暴露以下稳定边界：

```python
request = RenderRequest(
    scene_id="quadratic_formula",
    scene_class="QuadraticFormulaDerivation",
    source_path=Path("reference_scenes/formula/quadratic_formula.py"),
    profile=RenderProfile.PREVIEW,
    artifact_root=Path("runtime/phase4"),
)
result = RenderEngine().render(request)
```

- `RenderRequest` 拒绝绝对源码路径、`..`、未知档位、空 Scene ID 和非法类名。
- `RenderResult` 为带判别字段的成功/失败结果；调用方不解析日志文本来判断状态。
- 成功结果包含缓存键、是否缓存命中、四种产物相对路径及经过校验的元数据。
- 失败结果包含稳定的 `RenderFailureCode`、阶段、简明消息、退出码（若有）和日志相对路径；不得返回模糊的 `INTERNAL_ERROR`。
- 内核允许注入命令执行器和时钟，确保失败路径可测试；默认实现使用 `subprocess.run` 参数数组，不经过 shell。

## 6. 固定渲染档位

| 档位 | Manim 参数 | 分辨率 | 帧率 | 超时 |
|---|---|---:|---:|---:|
| preview | `-ql` | 854×480 | 15 FPS | 60 秒 |
| final | `-qh` | 1920×1080 | 60 FPS | 300 秒 |

两档均使用 Cairo、MP4、固定随机种子 `0` 和显式 `--media_dir`/`--output_file`。48 次验收禁用 Manim partial-movie 缓存；产品级同输入复用由内核缓存键控制。

## 7. 缓存键

缓存键为以下规范化 JSON 的 SHA-256：

- 契约版本 `phase4-render-v1`
- Scene ID 与类名
- 源码 SHA-256
- profile 名称及完整解析参数（分辨率、帧率、renderer、seed）
- Manim 版本与固定镜像 digest

路径、时间戳、artifact root 和宿主机用户名不得进入缓存键。相同内容和参数必须得到相同键；任一可观察渲染输入变化必须改变键。

## 8. 产物与元数据

每个缓存键使用独立目录，成功发布前先写临时目录，再原子重命名。目录最终必须包含：

- `video.mp4`
- `thumbnail.jpg`
- `render.log`
- `metadata.json`

元数据至少包含：规格版本、Scene ID/类名、profile、Manim 版本、镜像 digest、源码哈希、缓存键、开始/结束 UTC 时间、墙钟渲染时长、视频时长、帧数、宽高、帧率、四个产物的字节数和 SHA-256。`metadata.json` 的自哈希不写入自身；产物清单对 metadata 只记录字节数。

## 9. 失败分类

稳定失败码：

- `INVALID_REQUEST`
- `SOURCE_NOT_FOUND`
- `DOCKER_UNAVAILABLE`
- `CONTAINER_START_FAILED`
- `RENDER_TIMEOUT`
- `MANIM_RENDER_FAILED`
- `MISSING_VIDEO`
- `EMPTY_VIDEO`
- `FFPROBE_FAILED`
- `ZERO_FRAMES`
- `INVALID_DURATION`
- `FFMPEG_FAILED`
- `MISSING_THUMBNAIL`
- `ARTIFACT_IO_FAILED`

失败必须保留日志并清理未发布的临时产物。未知 Python 异常不得被吞掉或改写成模糊内部错误，而应向编程调用方抛出，由测试暴露缺失分类。

## 10. 测试策略

- 父级单元测试：档位不可变、请求校验、缓存键、命令数组、元数据校验和每种失败映射。
- Scene 静态测试：正好 12 个清单项、类名唯一、每个文件一个 Scene、类别与目录一致。
- Agent C 黑盒测试：使用临时目录和可控执行器验证成功发布、缓存命中、失败清理与日志保留。
- 真 Docker 验收：先环境探测；然后执行 36 次 preview 和 12 次 final，逐次记录命令、退出码、耗时、产物哈希和探测结果。
- 重复性：同 Scene/profile 的视频必须具有相同视频时长、帧数、分辨率和帧率；文件哈希差异单独报告，不把容器/编码元数据差异误判为视觉失败。

## 11. 成功标准

- 12 个参考 Scene 数量、类别和清单完全匹配。
- 48/48 真渲染成功，每次均有四种有效产物且无零帧、空视频或异常时长。
- 36 次 preview 的中位墙钟时间不超过 60 秒。
- 相同输入缓存键稳定；源码、档位或固定渲染参数改变时缓存键改变。
- 所有注入失败均映射到明确失败码，日志可定位，临时产物不冒充成功缓存。
- 父 agent 完成代码审查、全量 pytest、Ruff、契约同步检查和 12 个 Scene 的缩略图抽样。

## 12. 命令

```bash
uv run pytest -s -q tests/phase4
uv run ruff check apps/runner reference_scenes tests/phase4 benchmarks/phase4
uv run python benchmarks/phase4/run_acceptance.py --artifact-root runtime/phase4-acceptance
uv run python benchmarks/phase4/summarize.py runtime/phase4-acceptance/runs.jsonl
```

## 13. 官方依据

- ManimCE 0.20.1 配置与 CLI：https://docs.manim.community/en/v0.20.1/guides/configuration.html
- ManimCE 0.20.1 `ManimConfig`：https://docs.manim.community/en/v0.20.1/reference/manim._config.utils.ManimConfig.html
- ManimCE Docker：https://docs.manim.community/en/v0.20.1/installation/docker.html
- PyAV Streams：https://pyav.org/docs/stable/api/stream.html
- PyAV VideoFrame：https://pyav.org/docs/stable/api/video.html
