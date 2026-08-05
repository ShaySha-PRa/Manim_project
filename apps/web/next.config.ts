import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  agentRules: false,
  allowedDevOrigins: ["<WSL_IP>"],
  output: "standalone",
  transpilePackages: ["@manim-workbench/contracts"],
};

export default nextConfig;
