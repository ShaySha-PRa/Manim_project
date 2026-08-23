import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AppHeader } from "../components/auth/app-header";

import "./styles.css";

export const metadata: Metadata = {
  title: {
    default: "Manim 科学与技术动画工作台",
    template: "%s · Manim 科学与技术动画工作台",
  },
  description: "用自然语言生成可审阅、可渲染的科学与技术动画。",
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
