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
    bg: "#f7f7f8",
    rail: "#efeff1",
    surface: "#fcfcfd",
    raised: "#ffffff",
    subtle: "#f0f0f2",
    text: "#25262b",
    muted: "#64656e",
    border: "#e2e2e6",
    borderStrong: "#bcbcc5",
    accent: "#07765f",
    accentSoft: "#e2f2eb",
    success: "#26754d",
    warning: "#946016",
    warningSoft: "#fcf3e2",
    danger: "#b64040",
    dangerSoft: "#fceeee",
  },
  dark: {
    bg: "#18191b",
    rail: "#121315",
    surface: "#1c1d20",
    raised: "#252629",
    subtle: "#232427",
    text: "#e3e3e7",
    muted: "#aaabb3",
    border: "#303136",
    borderStrong: "#4c4e56",
    accent: "#81c5b1",
    accentSoft: "#243630",
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
        borderRadius: 7,
        controlHeight: 32,
        fontSize: 13,
        fontFamily:
          '"Segoe UI Variable Text", "Segoe UI", "Microsoft YaHei UI", sans-serif',
        motionDurationMid: "0.2s",
        motionEaseInOut: "cubic-bezier(0.2, 0.8, 0.2, 1)",
      },
      components: {
        Button: {
          primaryColor: dark ? "#16261e" : "#ffffff",
          primaryShadow: "inset 0 1px 0 #ffffff18, 0 1px 2px #00000014",
          defaultShadow: "inset 0 1px 0 #ffffff05, 0 1px 2px #00000008",
          defaultBg: p.raised,
          defaultBorderColor: p.border,
          defaultHoverBg: p.subtle,
          defaultHoverColor: p.text,
          defaultHoverBorderColor: p.borderStrong,
          defaultActiveBg: p.subtle,
          defaultActiveColor: p.text,
          defaultActiveBorderColor: p.borderStrong,
          textHoverBg: p.subtle,
        },
        Drawer: { colorBgElevated: p.surface },
        Modal: { contentBg: p.raised, headerBg: p.raised, titleFontSize: 15 },
      },
    },
  };
}
