import Link from "next/link";

export function AppHeader() {
  return (
    <header className="app-header">
      <div className="app-header__content">
        <Link aria-label="Manim 科学与技术动画工作台首页" className="app-brand" href="/">
          <span aria-hidden="true" className="app-brand__mark">
            ∿
          </span>
          <span>Manim 工作台</span>
        </Link>
        <nav aria-label="主导航" className="app-nav">
          <Link href="/workbench">工作台</Link>
        </nav>
      </div>
    </header>
  );
}
