import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export function rendererManualChunks(id: string) {
  const normalizedId = id.replaceAll("\\", "/");
  if (!normalizedId.includes("/node_modules/")) {
    return undefined;
  }
  if (
    normalizedId.includes("/node_modules/react") ||
    normalizedId.includes("/node_modules/react-dom") ||
    normalizedId.includes("/node_modules/scheduler")
  ) {
    return "react";
  }
  if (normalizedId.includes("/node_modules/lucide-react/")) {
    return "icons";
  }
  return "vendor";
}

export default defineConfig({
  base: "./",
  plugins: [react()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    chunkSizeWarningLimit: 800,
    rollupOptions: {
      output: {
        manualChunks: rendererManualChunks,
      },
    },
  },
});
