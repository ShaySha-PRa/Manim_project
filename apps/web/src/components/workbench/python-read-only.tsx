import type { CodeVersion } from "@manim-workbench/contracts";

import { workbenchApi } from "../../lib/api/client";
import styles from "../../app/workbench/workbench.module.css";

export function PythonReadOnly({ codeVersion }: { codeVersion: CodeVersion | null }) {
  if (!codeVersion) return <p className={styles.muted}>生成 CodeVersion 后，这里将显示只读源码。</p>;
  const sourceUrl = `${workbenchApi.baseUrl}/api/v1/workspace/code-versions/${codeVersion.id}/source`;

  return (
    <details className={styles.pythonPanel}>
      <summary>高级：只读 Python 源码（CodeVersion v{codeVersion.version}）</summary>
      <p>源码只用于查看或下载，不能在浏览器中编辑或执行。</p>
      <a href={`${sourceUrl}?download=true`}>下载 Python 文件</a>
      <pre><code>{codeVersion.source_code}</code></pre>
    </details>
  );
}
