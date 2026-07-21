import { defineConfig } from "vite";

export default defineConfig({
  build: {
    outDir: "../runtime/frontend-dist",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
  },
});
