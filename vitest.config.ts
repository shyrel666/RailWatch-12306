import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    // DOM suites load Ant Design; bound parallel workers on shared Windows runners.
    maxWorkers: 2,
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    setupFiles: ["src/test/setupDom.ts"],
  },
});
