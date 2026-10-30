import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // T3 钉死三配置：纯静态 export（nginx 直接托管 out/）
  output: "export",
  images: { unoptimized: true },
  trailingSlash: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
