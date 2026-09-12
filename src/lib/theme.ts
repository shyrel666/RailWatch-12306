import { theme, type ThemeConfig } from "antd";

export type ThemeMode = "system" | "light" | "dark";
export const themeOptions: { value: ThemeMode; label: string }[] = [
  { value: "system", label: "跟随系统" },
  { value: "light", label: "明亮" },
  { value: "dark", label: "深色" },
];
export function normalizeTheme(value: unknown): ThemeMode {
  return value === "light" || value === "dark" ? value : "system";
}
const palettes = {
  light: {
    bg: "#f5f6f5",
    rail: "#eef1ef",
    surface: "#ffffff",
    raised: "#ffffff",
    subtle: "#f0f3f1",
    text: "#202923",
    muted: "#606e65",
    border: "#dce3de",
    accent: "#07765f",
    accentSoft: "#e2f2eb",
    success: "#26754d",
    warning: "#946016",
    warningSoft: "#fcf3e2",
    danger: "#b64040",
    dangerSoft: "#fceeee",
  },
  dark: {
    bg: "#191d1b",
    rail: "#151917",
    surface: "#202622",
    raised: "#29312c",
    subtle: "#272e29",
    text: "#e9efeB",
    muted: "#a6b3a9",
    border: "#354039",
    accent: "#69d5b4",
    accentSoft: "#233e33",
    success: "#8bd4a7",
    warning: "#e5bc73",
    warningSoft: "#393123",
    danger: "#f19b9b",
    dangerSoft: "#3d2929",
  },
};
export function getTheme(dark: boolean): {
  config: ThemeConfig;
  variables: Record<string, string>;
} {
  const p = palettes[dark ? "dark" : "light"];
  return {
    variables: Object.fromEntries(
      Object.entries(p).map(([key, value]) => [
        `--${key.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`)}`,
        value,
      ]),
    ),
    config: {
      algorithm: dark ? theme.darkAlgorithm : theme.defaultAlgorithm,
      token: {
        colorPrimary: p.accent,
        colorInfo: p.accent,
        colorSuccess: p.success,
        colorWarning: p.warning,
        colorError: p.danger,
        colorBgBase: p.bg,
        colorBgContainer: p.surface,
        colorBgElevated: p.raised,
        colorText: p.text,
        colorTextSecondary: p.muted,
        colorBorder: p.border,
        colorBorderSecondary: p.border,
        borderRadius: 8,
        controlHeight: 36,
        fontSize: 14,
        fontFamily:
          '"Segoe UI", "Microsoft YaHei UI", "Noto Sans SC", sans-serif',
        motionDurationMid: "0.16s",
      },
      components: {
        Button: {
          primaryColor: dark ? "#16261e" : "#ffffff",
          primaryShadow: "none",
          defaultShadow: "none",
        },
        Drawer: { colorBgElevated: p.surface },
      },
    },
  };
}
