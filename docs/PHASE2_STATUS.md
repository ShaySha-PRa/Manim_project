# Phase 2 验收报告

## 结论

Phase 2 已通过，选择 Manim Community `0.20.1`。ManimGL 因无头启动失败且未完成 12/12 门禁被淘汰；项目发起人明确要求停止 GL，不再重试。

## 对比结果

| 项目 | ManimCE | ManimGL |
|---|---:|---:|
| 固定候选 | 0.20.1 官方镜像 | Git tag v1.7.2 自建镜像 |
| 完成运行 | 12/12 | 0/2 成功，之后停止 |
| 首次场景成功 | 6/6 | 0/1 |
| 平均低清耗时 | 7.543 秒 | 不可计分 |
| 最终视频 | 6 类、12 个 | 0 |
| 状态 | 合格 | 淘汰 |

ManimCE 加权分为 95.95。ManimGL 未达到稳定性前置门槛，因此不计算综合分，也不与 CE 比较速度。

## ManimCE 版本锁定

- Image digest：`manimcommunity/manim@sha256:f18f53f2e4eaf2ea41713437d34363fb3f5cc6008b03fd798676ac0359396c3b`
- Python：3.14.3
- Video runtime：PyAV 16.1.0；libavcodec 62.11.100；libavformat 62.3.100
- LaTeX：pdfTeX 1.40.28，TeX Live 2025
- Fonts：Noto Sans Regular、Noto Serif Regular、Noto Mono Regular

## 验证范围

- 两次独立运行各自使用单独媒体目录，关闭 Manim 动画缓存。
- 最终基准前清空本地 artifacts，避免复用此前 TeX/视频产物。
- 每次成功都同时要求退出码 0、MP4 存在和 SHA-256 可计算。
- 父 agent 检查了六类最终帧；数学对象均完整，参数和面积场景存在轻微标签遮挡，已反映在视觉分数中。

## 保存位置

- CE 结果：`benchmarks/phase2/results/manimce-summary.json`
- GL 失败：`benchmarks/phase2/results/manimgl-failure.json`
- 架构决策：`docs/decisions/0001-select-manim-community.md`

完整视频和日志保留在本地忽略目录 `benchmarks/phase2/*/artifacts/`，不提交 Git。
