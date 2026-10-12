import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// 开发时把后端请求代理到 FastAPI，避免配置跨域。
// 后端换了地址或端口，改这里即可（也可以用 `vite --mode` 拆分多环境配置）。
const backend = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: backend, changeOrigin: true },
      "/health": { target: backend, changeOrigin: true },
    },
  },
});
