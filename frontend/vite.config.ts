import { defineConfig } from "vite";

// 共享服务器上 8000 可能被其他用户占用；用 QUANT_API_TARGET 覆盖代理目标。
const apiTarget = process.env.QUANT_API_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  server: {
    port: 5173,
    strictPort: true,
    proxy: { "/api": apiTarget },
  },
  preview: { proxy: { "/api": apiTarget } },
});
