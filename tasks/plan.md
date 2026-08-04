# Implementation Plan: Phase 4 可信渲染内核

## Overview

以 Phase 2 固定的 ManimCE 0.20.1 镜像和 Phase 3 领域边界为基础，先建立父级渲染契约和失败门禁，再并行生产两类可信 Scene 与独立黑盒验收，最后由父 agent 合并、审查并完成 48 次真实渲染。

## Architecture Decisions

- 同步渲染内核只属于 Host Runner；API、Redis 和数据库编排留到 Phase 5。
- 产品缓存键独立于 Manim partial cache；真实 48 次验收禁用后者，避免缓存掩盖稳定性。
- preview 固定 `-ql`，final 固定 `-qh`；所有参数、镜像和 seed 进入缓存契约。
- MP4、缩略图、日志和元数据原子发布；固定镜像内使用 PyAV/FFmpeg 库做探测和抽帧，失败临时目录不得成为缓存命中。
- 失败使用封闭枚举，未知异常向上抛出以暴露未建模错误。

## Dependency Graph

```text
规格与接口 + 父级红灯测试
    ├── 父 agent：渲染内核
    ├── Agent A：6 公式 Scene
    ├── Agent B：6 函数 Scene
    └── Agent C：黑盒/失败/重复性/性能工具
             ↓
        父 agent 审查与整合
             ↓
        48 次真渲染验收
             ↓
        状态报告与 Phase 4 门禁
```

## Task List

### Slice 1：父级规格、接口与红灯测试

- [x] 固化 `docs/PHASE4_SPEC.md`、48 次矩阵和互斥目录所有权。
- [x] 写入 RenderRequest/Result、档位、缓存、元数据和失败分类的失败测试。
- [x] 运行聚焦测试并确认因 Phase 4 模块尚不存在而失败。

### Slice 2：并行生产

- [ ] 父 agent 实现渲染接口、命令执行、视频探测、缩略图、原子产物和缓存。
- [ ] Terra Agent A 只实现 `reference_scenes/formula/` 的 6 个 Scene。
- [ ] Terra Agent B 只实现 `reference_scenes/functions/` 的 6 个 Scene。
- [ ] Terra Agent C 只实现 `tests/phase4/blackbox/` 与 `benchmarks/phase4/`。

### Slice 3：整合与修复

- [ ] 父 agent 按正确性、可读性、架构、安全和性能五轴审查三个 agent 的产物。
- [ ] 运行 Phase 4 聚焦测试和 Ruff，修复 Required/Critical 问题。
- [ ] 运行全量 Python 测试与既有契约同步测试，确认 Phase 0–3 无回归。

### Slice 4：真实渲染门禁

- [ ] 环境探测固定镜像、Docker、Manim、FFmpeg、LaTeX 和字体。
- [ ] 完成 12 Scene × 3 preview，无缓存，共 36 次。
- [ ] 完成 12 Scene × 1 final，无缓存，共 12 次。
- [ ] 汇总成功率、重复性和 preview 中位耗时，抽样全部 12 张缩略图。
- [ ] 更新 `docs/PHASE4_STATUS.md`、`docs/PROJECT_PLAN.md` 和 `tasks/todo.md`。

## Checkpoints

- Slice 1：测试确实红灯且失败原因是缺少 Phase 4 实现。
- Slice 2：三个子 agent 文件集合完全互斥，父级公共契约未被改写。
- Slice 3：全部自动测试与静态检查通过。
- Slice 4：48/48 成功且 preview 中位数 ≤ 60 秒，才可声明 Phase 4 完成。

## Risks and Mitigations

| 风险 | 影响 | 缓解措施 |
|---|---|---|
| 48 次高清渲染耗时较长 | 门禁耗时 | 先完成全部 preview，再执行一次 final；逐次追加结果以便中断恢复 |
| Docker 组在非登录 shell 不生效 | 无法调用 daemon | 复用已验证的 `sg docker -c` 入口，并在正式渲染前探测 |
| Scene 过长拖垮性能门禁 | preview 超 60 秒 | Scene 动画时长控制在教学可读的 4–12 秒，避免无意义等待 |
| 视频字节哈希因编码元数据变化 | 重复性误报 | 强制比对可观察流属性，同时单独报告文件哈希差异 |
| 子 agent 修改共享契约 | 并行冲突 | 提示中明确只写目录，父 agent 用 `git diff --name-only` 审核越界 |

## Official Sources

- https://docs.manim.community/en/v0.20.1/guides/configuration.html
- https://docs.manim.community/en/v0.20.1/reference/manim._config.utils.ManimConfig.html
- https://docs.manim.community/en/v0.20.1/installation/docker.html
- https://pyav.org/docs/stable/api/stream.html
- https://pyav.org/docs/stable/api/video.html
