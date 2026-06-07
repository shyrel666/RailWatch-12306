import { describe, expect, test } from "vitest";
import viteConfig from "../../vite.config";

describe("vite build config", () => {
  test("splits large renderer dependencies into stable chunks", async () => {
    const resolved = viteConfig;
    const output = Array.isArray(resolved.build?.rollupOptions?.output)
      ? resolved.build?.rollupOptions?.output[0]
      : resolved.build?.rollupOptions?.output;
    const manualChunks = output?.manualChunks;

    expect(typeof manualChunks).toBe("function");

    if (typeof manualChunks === "function") {
      expect(manualChunks("D:/app/node_modules/antd/es/button/index.js", { getModuleInfo: () => null, getModuleIds: function* () {} })).toBe("vendor");
      expect(manualChunks("D:/app/node_modules/react-dom/client.js", { getModuleInfo: () => null, getModuleIds: function* () {} })).toBe("react");
      expect(manualChunks("D:/app/node_modules/lucide-react/dist/esm/icons/play.js", { getModuleInfo: () => null, getModuleIds: function* () {} })).toBe("icons");
      expect(manualChunks("D:/app/node_modules/zustand/esm/index.mjs", { getModuleInfo: () => null, getModuleIds: function* () {} })).toBe("vendor");
    }
  });
});
