import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  transpilePackages: [
    "@excalidraw/excalidraw",
    "@excalidraw/mermaid-to-excalidraw",
  ],
};

export default nextConfig;
