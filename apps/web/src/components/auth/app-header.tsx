import Link from "next/link";

import { isFeatureFlagEnabled } from "../../lib/feature-flags";

export function AppHeader() {
  const labEnabled = isFeatureFlagEnabled(process.env.NEXT_PUBLIC_EXPERIMENT_LAB_ENABLED);
  const studioEnabled = isFeatureFlagEnabled(process.env.NEXT_PUBLIC_STUDIO_ENABLED);

  return (
    <header className="app-header">
      <div className="app-header__content">
        <Link aria-label="Manim 数学动画工作台首页" className="app-brand" href="/">
          <span aria-hidden="true" className="app-brand__mark">
            ∿
          </span>
          <span>Manim 工作台</span>
        </Link>
        <nav aria-label="主导航" className="app-nav">
          <Link href="/workbench">工作台</Link>
          {labEnabled ? <Link href="/lab">实验室</Link> : null}
          {studioEnabled ? <Link href="/studio">Studio</Link> : null}
          <Link href="/login">登录</Link>
        </nav>
      </div>
    </header>
  );
}
