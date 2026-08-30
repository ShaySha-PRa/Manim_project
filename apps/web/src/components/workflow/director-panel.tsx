import type { ReturnTypeVideoWorkflow } from "./workflow-editor";

import styles from "../../app/workflows/workflows.module.css";

export function DirectorPanel({ model }: { model: ReturnTypeVideoWorkflow }) {
  const plan = model.directorPlan;
  return (
    <section className={`${styles.panel} ${styles.directorPanel}`} aria-labelledby="director-title">
      <div className={styles.panelHeading}>
        <div>
          <p className={styles.eyebrow}>WORKFLOW DIRECTOR</p>
          <h2 id="director-title">一句话规划完整视频</h2>
        </div>
        <span className={styles.badge}>{plan?.status ?? "draft"}</span>
      </div>
      <p className={styles.hint}>
        描述整片要解释、计算和展示什么。Director 只拆分严格场景草稿，不写代码、不调用工具；应用后仍由现有教学/科研管线逐幕验证。
      </p>
      <label>
        完整视频目标
        <textarea
          rows={4}
          value={model.directorObjective}
          onChange={(event) => model.setDirectorObjective(event.target.value)}
          placeholder="例如：生成一段完整视频，解释 Lorenz 系统为什么具有初值敏感性，并展示真实计算轨迹和距离增长。"
        />
      </label>
      <div className={styles.actions}>
        <button type="button" disabled={model.busy || !model.projectId} onClick={() => void model.planWithDirector()}>
          自动拆分场景
        </button>
        <button
          type="button"
          disabled={model.busy || plan?.status !== "ready"}
          onClick={() => void model.applyDirectorPlan()}
        >
          应用为可编辑工作流
        </button>
      </div>
      {plan && <div aria-live="polite" className={styles.directorResult}>
        <p><strong>规划状态：</strong>{plan.status} · attempt {plan.attempt_count}</p>
        {plan.error_code && <p className={styles.error}>需要处理：{plan.error_code}</p>}
        {plan.draft && <>
          <p><strong>{plan.draft.global_brief.title}</strong> · {plan.draft.global_brief.target_duration_seconds}s · {plan.draft.scenes.length} 幕</p>
          <ol>{plan.draft.scenes.map((scene, index) => <li key={`${scene.title}-${index}`}>
            <strong>{scene.title}</strong> <span className={styles.badge}>{scene.pipeline_mode}</span>
            <span> {scene.target_duration_seconds}s — {scene.prompt}</span>
            {(scene.asset_requirements ?? []).length > 0 && <small>需要资产：{(scene.asset_requirements ?? []).join("、")}</small>}
          </li>)}</ol>
          {(plan.draft.confirmations ?? []).length > 0 && <div className={styles.blockers}>
            <strong>确认后才能应用</strong>
            <ul>{(plan.draft.confirmations ?? []).map((item) => <li key={`${item.code}-${item.scene_position}`}>{item.message}</li>)}</ul>
          </div>}
        </>}
      </div>}
    </section>
  );
}
