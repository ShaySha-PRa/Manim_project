# Phase 7 威胁模型

## 资产与信任边界

资产包括 DeepSeek 密钥、宿主文件与 Docker daemon、其他项目数据、数据库完整性、计算资源、
已发布视频和审计记录。用户 Prompt、ContentPlan 文本、参考 Scene 内容、DeepSeek 响应、
候选 Python、编译/Manim/沙箱日志全部是不可信数据。

信任边界按顺序为：API 输入 -> 持久化 ContentPlan -> DeepSeek -> JSON/Schema -> AST 安全门
-> 编译/Scene 预检 -> Phase 5 Runner/Docker -> 产物验证。任何后级控制都不能替代前级控制。

## 主要滥用案例与控制

| 威胁 | 滥用案例 | 强制控制 |
|---|---|---|
| 提示注入 | ContentPlan 要求忽略规则并读取密钥 | Prompt 不是边界；本地 AST 与沙箱失败关闭 |
| 任意代码执行 | 动态 import、dunder、反射、eval/exec/open | AST 节点、名称、属性、import 和调用白名单 |
| 数据泄露 | 读取 `.env`、宿主路径、网络外传 | 不向模型发送秘密；容器只读且 `--network none` |
| 绕过校验 | 编码危险名称、别名导入、链式属性 | 解析别名并拒绝未知符号、dunder 和动态调用 |
| 资源耗尽 | 巨型 AST、无限循环、超大对象或动画 | 源码/AST/深度上限；Phase 5 CPU、内存、PID、超时和输出限制 |
| 修复链泄露 | 把完整 Docker 日志、路径或令牌发回模型 | 分类、截断、正则脱敏；仅允许修复类别进入模型 |
| 重放与污染 | 跨 owner 使用 ContentPlan 或覆盖旧 CodeVersion | 四元组所有权校验；append-only CodeVersion；哈希绑定 |
| 策略失效 | 攻击漏过后继续生成 | 任一安全漏过触发全局 paused，必须人工复核恢复 |

## 安全不变量

1. 没有成功的静态安全报告，就不能创建 RenderJob。
2. 高风险安全违规永不进入自动修复；低风险静态契约偏差只允许无源码修复，任何未通过
   AST 门的候选源码都不回传模型。
3. 宿主进程永不 import、exec、eval 或运行候选源码。
4. 每次请求最多一次初始生成和两次修复。
5. 只有最终通过校验的源码进入不可变 CodeVersion。
6. 所有公开错误、数据库记录和评测报告均不含秘密、绝对路径或完整日志。
7. 确定性降级模板与完整生成使用同一安全和沙箱门。

## 失败关闭条件

- AST 解析异常、未知节点/名称/属性/API 或校验器内部异常；
- 模型响应不能严格解析；
- ContentPlan/Prompt/project/owner 不一致；
- 无法确认候选 SHA-256、Scene 唯一性或类名；
- 沙箱或策略状态不可用；
- 安全攻击集出现任何漏过。

## 明确剩余风险

- AST 白名单无法证明数学或教学正确性，必须由黄金集评分补足；
- Docker daemon 仍是宿主高权限组件，沿用 Phase 5 最小输入面和受控 WSL 用户；
- DeepSeek 可能产生结构不稳定输出，因此代码生成只依赖 Schema 语义，不依赖固定 Scene 数量；
- Manim/numpy 允许 API 内仍可能存在高成本表达式，由静态大小上限和沙箱资源限制共同约束；
- Phase 8 前 API 仍只允许私网和内部令牌使用。
