import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Alfa_Slab_One, Archivo_Narrow, Caveat_Brush, DM_Mono, Noto_Sans_SC } from "next/font/google";

import { AppHeader } from "../components/auth/app-header";

import "./styles.css";

const display = Alfa_Slab_One({
  weight: "400",
  subsets: ["latin"],
  variable: "--font-display",
  display: "swap",
});

const body = Archivo_Narrow({
  weight: ["400", "500", "600", "700"],
  subsets: ["latin"],
  variable: "--font-body",
  display: "swap",
});

const script = Caveat_Brush({
  weight: "400",
  subsets: ["latin"],
  variable: "--font-script",
  display: "swap",
});

const mono = DM_Mono({
  weight: ["400", "500"],
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
});

const cjk = Noto_Sans_SC({
  weight: ["400", "500", "700", "900"],
  variable: "--font-cjk",
  display: "swap",
  preload: false,
});

export const metadata: Metadata = {
  title: {
    default: "Manim 科研动画工作台",
    template: "%s · Manim 科研动画工作台",
  },
  description: "一句话变成可审阅、可渲染的科学动画。",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html
      className={`${display.variable} ${body.variable} ${script.variable} ${mono.variable} ${cjk.variable}`}
      lang="zh-CN"
    >
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
