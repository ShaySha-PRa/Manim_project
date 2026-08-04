import { CONTRACT_SCHEMA_VERSION } from "@manim-workbench/contracts";


const boundaries = [
  ["Web", "Next.js App Router 空壳"],
  ["API", "FastAPI 版本化健康检查"],
  ["Runner", "宿主机边界，尚未启用 Docker"],
  ["Contracts", `Schema ${CONTRACT_SCHEMA_VERSION}`],
] as const;


export default function Home() {
  return (
    <main>
      <section aria-labelledby="phase-title" className="panel">
        <p className="eyebrow">MANIM WORKBENCH</p>
        <h1 id="phase-title">Phase 3 工程骨架</h1>
        <p className="lede">
          当前只验证服务边界、领域契约和数据迁移。教学规划、代码生成与隔离渲染将在后续阶段接入。
        </p>
        <dl>
          {boundaries.map(([name, detail]) => (
            <div key={name}>
              <dt>{name}</dt>
              <dd>{detail}</dd>
            </div>
          ))}
        </dl>
        <p className="notice">尚无业务功能。这是有意保留的阶段边界。</p>
      </section>
    </main>
  );
}

