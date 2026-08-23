import type { ReactNode } from "react";

import { Panel } from "../ui/panel";

type AuthShellProps = {
  readonly children: ReactNode;
  readonly description: string;
  readonly eyebrow: string;
  readonly footer?: ReactNode;
  readonly title: string;
};

export function AuthShell({
  children,
  description,
  eyebrow,
  footer,
  title,
}: Readonly<AuthShellProps>) {
  return (
    <main className="auth-main" id="main-content">
      <div className="auth-layout">
        <aside aria-label="产品说明" className="auth-aside">
          <p className="auth-aside__index">01 / 安全入口</p>
          <div>
            <p className="eyebrow">ANIMATION AGENT</p>
            <h1>让一句话，成为可审阅的科学与技术动画。</h1>
            <p>
              从自然语言理解、必要计算和动画设计，到预览与终渲，每一步都保留版本、状态和可追溯产物。
            </p>
          </div>
          <dl className="auth-aside__facts">
            <div>
              <dt>输入</dt>
              <dd>自然语言 Prompt</dd>
            </div>
            <div>
              <dt>过程</dt>
              <dd>理解、计算与动画设计</dd>
            </div>
            <div>
              <dt>输出</dt>
              <dd>隔离渲染的视频产物</dd>
            </div>
          </dl>
        </aside>

        <Panel as="section" aria-labelledby="auth-title" className="auth-panel">
          <p className="eyebrow">{eyebrow}</p>
          <h2 id="auth-title">{title}</h2>
          <p className="auth-panel__description">{description}</p>
          {children}
          {footer ? <footer className="auth-panel__footer">{footer}</footer> : null}
        </Panel>
      </div>
    </main>
  );
}
