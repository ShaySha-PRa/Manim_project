import type { GlobalBrief } from "./types";

import styles from "../../app/workflows/workflows.module.css";

type Props = {
  brief: GlobalBrief;
  onChange: (brief: GlobalBrief) => void;
};

const formatEntries = (values: Readonly<Record<string, string | number>>) =>
  Object.entries(values).map(([key, value]) => `${key}=${value}`).join("\n");

const parseNotation = (value: string) => Object.fromEntries(
  value.split("\n").map((line) => line.split("=", 2).map((part) => part.trim()))
    .filter((pair): pair is [string, string] => pair.length === 2 && Boolean(pair[0] && pair[1])),
);

const parseParameters = (value: string) => Object.fromEntries(
  value.split("\n").map((line) => line.split("=", 2).map((part) => part.trim()))
    .filter((pair) => pair.length === 2 && Boolean(pair[0]) && Number.isFinite(Number(pair[1])))
    .map(([key, number]) => [key, Number(number)]),
);

export function GlobalBriefPanel({ brief, onChange }: Props) {
  const patch = (value: Partial<GlobalBrief>) => onChange({ ...brief, ...value });
  return (
    <section className={styles.panel} aria-labelledby="global-brief-title">
      <div className={styles.panelHeading}>
        <div><p className={styles.eyebrow}>GLOBAL BRIEF</p><h2 id="global-brief-title">全局视频设置</h2></div>
        <span className={styles.badge}>16:9</span>
      </div>
      <div className={styles.formGrid}>
        <label className={styles.wide}>视频标题<input value={brief.title} onChange={(event) => patch({ title: event.target.value })} /></label>
        <label>语言<select value={brief.language} onChange={(event) => patch({ language: event.target.value as GlobalBrief["language"] })}><option value="zh-CN">中文</option><option value="en-US">English</option></select></label>
        <label>统一风格<select value={brief.style_preset} onChange={(event) => patch({ style_preset: event.target.value as GlobalBrief["style_preset"] })}><option value="dark_scientific">深色科研</option><option value="light_academic">浅色学术</option><option value="minimal_math">极简数学</option><option value="presentation">演示文稿</option></select></label>
        <label>整片目标时长（秒）<input type="number" min={30} max={600} value={brief.target_duration_seconds} onChange={(event) => patch({ target_duration_seconds: Number(event.target.value) })} /></label>
        <label>背景颜色<input type="color" value={brief.background} onChange={(event) => patch({ background: event.target.value })} /></label>
        <label className={styles.wide}>统一色板（逗号分隔）<input value={brief.palette.join(", ")} onChange={(event) => patch({ palette: event.target.value.split(",").map((item) => item.trim()).filter(Boolean) })} /></label>
        <label className={styles.wide}>统一符号（每行 key=value）<textarea rows={3} value={formatEntries(brief.notation)} onChange={(event) => patch({ notation: parseNotation(event.target.value) })} placeholder="sigma=σ" /></label>
        <label className={styles.wide}>共享科学参数（每行 key=数值）<textarea rows={3} value={formatEntries(brief.scientific_parameters)} onChange={(event) => patch({ scientific_parameters: parseParameters(event.target.value) })} placeholder="rho=28" /></label>
      </div>
      <p className={styles.hint}>全局风格、符号和科学参数会进入每个场景的缓存键与 provenance。</p>
    </section>
  );
}
