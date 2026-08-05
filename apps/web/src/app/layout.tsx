import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AppHeader } from "../components/auth/app-header";

import "./styles.css";

export const metadata: Metadata = {
  title: {
    default: "Phase 8 · Manim 数学动画工作台",
    template: "%s · Manim 数学动画工作台",
  },
  description: "Phase 8：将数学教学意图转化为可审阅、可渲染的 Manim 动画。",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        <a className="skip-link" href="#main-content">
          跳至主要内容
        </a>
        <AppHeader />
        {children}
      </body>
    </html>
  );
}
