import type { NextConfig } from "next";

const allowedDevOrigins = (process.env.NEXT_ALLOWED_DEV_ORIGINS ?? "localhost,127.0.0.1")
  .split(",")
  .map((origin) => origin.trim())
  .filter(Boolean);

const nextConfig: NextConfig = {
  agentRules: false,
  allowedDevOrigins,
  output: "standalone",
  transpilePackages: ["@manim-workbench/contracts"],
};

export default nextConfig;
