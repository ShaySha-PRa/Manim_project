# Implementation Plan: Phase 2 Manim Engine Benchmark

## Overview

用同一测试契约并行评估 Manim Community 与 ManimGL。项目发起人已批准由两个 Terra 子 agent 分别实现引擎适配，父 agent 负责契约、证据核验、评分、选型与版本锁定。

## Architecture Decisions

- 两个引擎必须实现相同的 6 个教学意图场景，每个场景无头渲染两次。
- 引擎专属代码放在独立目录，运行结果统一写成 `result.json`，由父 agent 的单一评分器处理。
- 视频、日志和缓存属于本地基准产物，不提交 Git；源码、运行脚本、结果摘要和选型报告提交 Git。
- 固定发布版本：ManimCE `0.20.1`；ManimGL `1.7.2`。不使用移动的 `latest` 或 `master`。

## Task List

### Slice 1: 统一契约和评分器

- [x] 定义 6 个场景、12 次运行及统一结果格式。
- [x] 以测试固定淘汰、权重和 10 分以内优先 CE 的选择规则。
- [x] 提交可独立验证的评分器。

### Slice 2: 并行引擎基准

- [x] Terra-CE 实现 ManimCE 基准，父 agent 完成 12/12 实际运行。
- [x] Terra-GL 实现 ManimGL 基准，父 agent 记录重复无头启动失败并按用户决定停止。
- [x] 每个实现记录精确依赖、命令、日志、耗时和失败原因。

### Slice 3: 父 agent 核验与选型

- [x] 检查场景语义、真实运行和输出文件证据。
- [x] 应用淘汰门禁并完成人工视觉评分。
- [x] 输出选型报告，锁定引擎、视频运行库、LaTeX 和字体版本。
- [x] 更新项目计划、README 和任务清单。

## Checkpoints

- Slice 1：评分器测试通过，空结果或不完整结果不能过门禁。
- Slice 2：每个引擎恰好 12 条运行记录；失败也必须保留日志和退出码。
- Slice 3：报告可以从仓库内源码、摘要和命令复核，不把未执行基准写成成功。

## Risks and Mitigations

| 风险 | 影响 | 缓解措施 |
|---|---|---|
| Docker daemon 在当前会话不可访问 | 无法完成实际渲染 | 先完成可复现基准；尝试本地环境，否则把门禁标记为阻塞而不伪造结果 |
| ManimGL 需要 OpenGL 上下文 | 无头运行失败 | 使用软件渲染/Xvfb；把部署复杂度计入评分 |
| 两套 API 无法逐行同构 | 比较失真 | 比较教学意图和可观察输出，不比较源代码结构 |
| 首轮代码失败后被静默修复 | 首次成功率失真 | 保留首次尝试状态与原始日志 |

## Official Sources

- ManimCE Docker: https://docs.manim.community/en/stable/installation/docker.html
- ManimCE changelog: https://docs.manim.community/en/stable/changelog.html
- ManimCE sections: https://docs.manim.community/en/stable/guides/configuration.html
- ManimGL repository and CLI: https://github.com/3b1b/manim
