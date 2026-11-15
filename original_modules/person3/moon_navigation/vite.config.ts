import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The web app lives in src/web. In dev, /api is proxied to the Express service.
export default defineConfig({
  root: "src/web",
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api/": process.env.VITE_API_TARGET ?? "http://localhost:3003" },
  },
  build: { outDir: "../../dist/web", emptyOutDir: true },
});
