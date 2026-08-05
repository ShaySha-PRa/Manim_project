"use client";

import { useState } from "react";

import type { Audience, DerivationStyle } from "@manim-workbench/contracts";

import type { WorkbenchModel } from "./types";
import styles from "../../app/workbench/workbench.module.css";

const audiences: ReadonlyArray<[Audience, string]> = [
  ["primary_school", "小学"], ["middle_school", "初中"], ["high_school", "高中"],
  ["undergraduate", "本科"], ["general_audience", "通用受众"],
];

const stylesByGoal: ReadonlyArray<[DerivationStyle, string]> = [
  ["step_by_step", "逐步推导"], ["conceptual", "概念导向"],
  ["proof_oriented", "证明导向"], ["visual_intuition", "视觉直觉"],
];

export function ProjectPromptPanel({ model }: { model: WorkbenchModel }) {
  const [title, setTitle] = useState("");
  const [prompt, setPrompt] = useState("");
  const [audience, setAudience] = useState<Audience>("high_school");
  const [duration, setDuration] = useState(60);
  const [style, setStyle] = useState<DerivationStyle>("step_by_step");
  const [assumptions, setAssumptions] = useState("");

  const generate = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void model.generatePlan({
      prompt, audience, duration, style,
      assumptions: assumptions.split("\n").map((item) => item.trim()).filter(Boolean),
    });
  };

  return (
    <section className={styles.column} aria-labelledby="project-prompt-heading">
      <div className={styles.sectionHeading}>
        <p>01 · 创作输入</p><h2 id="project-prompt-heading">项目与 Prompt</h2>
      </div>
      <label className={styles.field}>
        <span>项目</span>
        <select
          value={model.activeProject?.id ?? ""}
          onChange={(event) => {
            const next = model.projects.find((project) => project.id === event.target.value);
            if (next) void model.loadProject(next);
          }}
          disabled={model.busy}
        >
          <option value="">选择项目</option>
          {model.projects.map((project) => <option key={project.id} value={project.id}>{project.title}</option>)}
        </select>
      </label>
      <form className={styles.inlineForm} onSubmit={(event) => { event.preventDefault(); void model.createProject(title); }}>
        <label className={styles.field}><span>新项目名称</span>
          <input value={title} maxLength={120} onChange={(event) => setTitle(event.target.value)} placeholder="例如：二次函数的顶点" />
        </label>
        <button type="submit" disabled={model.busy || !title.trim()}>创建项目</button>
      </form>
      <form className={styles.form} onSubmit={generate}>
        <label className={styles.field}><span>教学 Prompt</span>
          <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} rows={5} maxLength={4_000}
            placeholder="描述要讲解的数学问题、已知条件和教学重点。" required />
        </label>
        <div className={styles.fieldRow}>
          <label className={styles.field}><span>受众</span><select value={audience} onChange={(event) => setAudience(event.target.value as Audience)}>{audiences.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
          <label className={styles.field}><span>时长（秒）</span><input type="number" min={30} max={180} value={duration} onChange={(event) => setDuration(Number(event.target.value))} /></label>
        </div>
        <label className={styles.field}><span>推导风格</span><select value={style} onChange={(event) => setStyle(event.target.value as DerivationStyle)}>{stylesByGoal.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
        <fieldset className={styles.choiceGroup}><legend>动画类型</legend>
          <label><input type="radio" checked={model.category === "formula_derivation"} onChange={() => model.setCategory("formula_derivation")} name="category" />公式推导</label>
          <label><input type="radio" checked={model.category === "function_visualization"} onChange={() => model.setCategory("function_visualization")} name="category" />函数可视化</label>
        </fieldset>
        <label className={styles.field}><span>明确假设（每行一条，可选）</span>
          <textarea value={assumptions} rows={3} onChange={(event) => setAssumptions(event.target.value)} placeholder="例如：已知 a ≠ 0" />
        </label>
        <button className={styles.primaryButton} type="submit" disabled={model.busy || !model.activeProject}>生成 ContentPlan</button>
      </form>
    </section>
  );
}
