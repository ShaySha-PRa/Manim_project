"use client";

import type { FormulaStep } from "@manim-workbench/contracts";

import type { EditableScene, PlanEditor } from "../../hooks/workbench/use-workbench";
import type { WorkbenchModel } from "./types";
import styles from "../../app/workbench/workbench.module.css";

const audiences = [
  ["primary_school", "小学"], ["middle_school", "初中"], ["high_school", "高中"],
  ["undergraduate", "本科"], ["general_audience", "通用受众"],
] as const;

const derivationStyles = [
  ["step_by_step", "逐步推导"], ["conceptual", "概念导向"],
  ["proof_oriented", "证明导向"], ["visual_intuition", "视觉直觉"],
] as const;

function replaceScene(editor: PlanEditor, index: number, scene: EditableScene): PlanEditor {
  return { ...editor, scenes: editor.scenes.map((current, cursor) => cursor === index ? scene : current) };
}

function SceneEditor({ scene, index, update }: {
  scene: EditableScene; index: number; update: (scene: EditableScene) => void;
}) {
  const updateStep = (stepIndex: number, next: FormulaStep) => update({
    ...scene, formula_steps: scene.formula_steps.map((step, cursor) => cursor === stepIndex ? next : step),
  });
  return (
    <fieldset className={styles.sceneCard}>
      <legend>场景 {index + 1}</legend>
      <label className={styles.field}><span>教学目标</span><input value={scene.teaching_goal} onChange={(event) => update({ ...scene, teaching_goal: event.target.value })} /></label>
      {scene.formula_steps.map((step, stepIndex) => (
        <div className={styles.formulaStep} key={`${index}-${stepIndex}`}>
          <label className={styles.field}><span>公式步骤</span><input value={step.expression} onChange={(event) => updateStep(stepIndex, { ...step, expression: event.target.value })} placeholder="例如：y = ax² + bx + c" /></label>
          <label className={styles.field}><span>解释</span><input value={step.explanation} onChange={(event) => updateStep(stepIndex, { ...step, explanation: event.target.value })} placeholder="说明此公式的含义" /></label>
          {scene.formula_steps.length > 1 && <button type="button" className={styles.textButton} onClick={() => update({ ...scene, formula_steps: scene.formula_steps.filter((_, cursor) => cursor !== stepIndex) })}>删除步骤</button>}
        </div>
      ))}
      <button type="button" className={styles.textButton} onClick={() => update({ ...scene, formula_steps: [...scene.formula_steps, { expression: "", explanation: "" }] })}>添加公式步骤</button>
      <label className={styles.field}><span>视觉意图</span><textarea rows={2} value={scene.visual_intent} onChange={(event) => update({ ...scene, visual_intent: event.target.value })} /></label>
      <label className={styles.field}><span>讲述提示</span><textarea rows={2} value={scene.narration_placeholder} onChange={(event) => update({ ...scene, narration_placeholder: event.target.value })} /></label>
    </fieldset>
  );
}

export function ContentPlanEditor({ model }: { model: WorkbenchModel }) {
  const editor = model.planEditor;
  if (!editor) {
    return <section className={styles.column}><div className={styles.sectionHeading}><p>02 · 教学编排</p><h2>ContentPlan</h2></div><p className={styles.empty}>从左栏生成 ContentPlan 后，可在此确认和编辑教学结构。</p></section>;
  }
  const update = (next: PlanEditor) => model.setPlanEditor(next);
  const updateScene = (index: number, scene: EditableScene) => update(replaceScene(editor, index, scene));

  return (
    <section className={styles.column} aria-labelledby="content-plan-heading">
      <div className={styles.sectionHeading}><p>02 · 教学编排</p><h2 id="content-plan-heading">ContentPlan</h2></div>
      <p className={styles.versionLabel}>当前编辑 v{model.activePlan?.version}；保存会创建不可变的新版本。</p>
      <div className={styles.fieldRow}>
        <label className={styles.field}><span>标题</span><input value={editor.title} onChange={(event) => update({ ...editor, title: event.target.value })} /></label>
        <label className={styles.field}><span>时长（秒）</span><input type="number" min={30} max={180} value={editor.target_duration_seconds} onChange={(event) => update({ ...editor, target_duration_seconds: Number(event.target.value) })} /></label>
      </div>
      <div className={styles.fieldRow}>
        <label className={styles.field}><span>受众</span><select value={editor.audience} onChange={(event) => update({ ...editor, audience: event.target.value as PlanEditor["audience"] })}>{audiences.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <label className={styles.field}><span>推导风格</span><select value={editor.derivation_style} onChange={(event) => update({ ...editor, derivation_style: event.target.value as PlanEditor["derivation_style"] })}>{derivationStyles.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      </div>
      <label className={styles.field}><span>明确假设（每行一条）</span><textarea rows={3} value={editor.explicit_assumptions.join("\n")} onChange={(event) => update({ ...editor, explicit_assumptions: event.target.value.split("\n") })} /></label>
      {editor.scenes.map((scene, index) => <SceneEditor key={scene.scene_number} scene={scene} index={index} update={(next) => updateScene(index, next)} />)}
      <div className={styles.actionRow}>
        <button type="button" onClick={() => update({ ...editor, scenes: [...editor.scenes, model.blankScene(editor.scenes.length + 1)] })}>添加场景</button>
        <button className={styles.primaryButton} type="button" disabled={model.busy} onClick={() => void model.savePlan()}>保存为新版本</button>
      </div>
      <VersionHistory model={model} />
    </section>
  );
}

function VersionHistory({ model }: { model: WorkbenchModel }) {
  return (
    <section className={styles.history} aria-label="版本历史">
      <h3>版本历史</h3>
      <p>Prompt：{model.prompts.map((prompt) => `v${prompt.version}`).join(" · ") || "尚无版本"}</p>
      {model.promptCursor !== null && <button type="button" className={styles.textButton} onClick={() => void model.loadMorePrompts()}>加载更多 Prompt 版本</button>}
      <ul>{model.plans.map((plan) => <li key={plan.id}><button type="button" className={styles.textButton} aria-current={plan.id === model.activePlan?.id} onClick={() => model.selectPlan(plan)}>ContentPlan v{plan.version}</button></li>)}</ul>
      {model.planCursor !== null && <button type="button" className={styles.textButton} onClick={() => void model.loadMorePlans()}>加载更多 ContentPlan 版本</button>}
      {model.codeVersion && <p>当前 CodeVersion：v{model.codeVersion.version}</p>}
    </section>
  );
}
