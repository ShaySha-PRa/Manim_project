import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  agentRules: false,
  output: "standalone",
  transpilePackages: ["@manim-workbench/contracts"],
};

export default nextConfig;
