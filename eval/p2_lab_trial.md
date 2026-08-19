# Animation Agent V2 P2 实验室试用协议

本文件是**本地实验室 harness**，不是外部科研用户研究。仓库里没有真实受试者、访谈记录或现场试用人数。

## 目的

在封闭 prompt 集上重复测量：

1. ToolRun 科学断言是否成立（科学正确率）；
2. 非预期 `FAILED` 是否低于 1%；
3. 每个 `ready` IR 能否同时 lowering 到 Manim Python 与 Web JSON。

## 怎么跑

在仓库根目录：

```bash
uv run python scripts/agent_p2_trial.py
```

或只跑验收门：

```bash
uv run python scripts/agent_p2_acceptance.py
```

数据来自 `eval/agent_p2_benchmark.jsonl`（100–300 条）。计算产物共用一个 `output_root`，相同 `{op, params, input}` 的 npz 会命中 cache。

## 记录什么

脚本打印 JSON，字段包括 `science_rate`、`fail_rate`、`cross_backend_rate`、`meets_p2_gates`。`external_user_study` 恒为 `false`。

## 不宣称

- 没有 N 名科研用户完成试用；
- 没有可用性问卷或现场反馈；
- Web backend 是 IR 的 JSON 预览 lowering，不是 Blender，也不替代 Docker Manim 出片。
