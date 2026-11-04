import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath } from "node:url";

export default defineConfig({
  base: "./",
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: [
      { find: "@", replacement: fileURLToPath(new URL("./src", import.meta.url)) },
      // Trim @pierre/diffs' Shiki registries to what the app uses (see src/shims).
      { find: /^shiki\/langs$/, replacement: fileURLToPath(new URL("./src/shims/shiki-langs.ts", import.meta.url)) },
      { find: /^@pierre\/theming\/themes$/, replacement: fileURLToPath(new URL("./src/shims/pierre-themes.ts", import.meta.url)) },
    ],
  },
  worker: { format: "es" },
  build: { outDir: "dist", chunkSizeWarningLimit: 4096 },
});
