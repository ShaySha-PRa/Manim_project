import type { Metadata } from "next";
import type { ReactNode } from "react";

import "./styles.css";


export const metadata: Metadata = {
  title: "Manim 数学动画工作台",
  description: "Phase 3 engineering skeleton",
};


export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}

