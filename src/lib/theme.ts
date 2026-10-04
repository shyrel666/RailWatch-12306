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
export const fontFamily =
  '"Segoe UI Variable Text", "Segoe UI", -apple-system, BlinkMacSystemFont, "Microsoft YaHei UI", "PingFang SC", "Noto Sans SC", sans-serif';
export const monoFontFamily =
  '"Cascadia Mono", "SF Mono", ui-monospace, Menlo, Consolas, monospace';
// Indigo marks what can be clicked; signal colors (success / warning / danger)
// only report state. The departure board stays dark in both themes.
const palettes = {
  light: {
    bg: "#f4f3ef",
    rail: "#f4f3ef",
    surface: "#ffffff",
    raised: "#ffffff",
    subtle: "#efede7",
    hover: "#e9e7e0",
    text: "#18191d",
    muted: "#63625d",
    faint: "#8f8d87",
    border: "#e4e1d9",
    borderStrong: "#cfccc3",
    accent: "#2b47d1",
    accentHover: "#2239b4",
    accentText: "#2b47d1",
    onAccent: "#ffffff",
    accentSoft: "#e8ebfb",
    success: "#0f7a43",
    successSoft: "#e2f2e8",
    warning: "#985b00",
    warningSoft: "#fbefd9",
    danger: "#c0352a",
    dangerSoft: "#fbe7e4",
    board: "#15171a",
    boardRaised: "#1d2024",
    boardLine: "#30333a",
    boardText: "#f2efe8",
    boardMuted: "#9b9ea5",
    led: "#ffb224",
    ledGo: "#5fdc9b",
    ledStop: "#ff8a7f",
    cardRing: "0 0 0 1px #0000000f, 0 1px 2px #0000000a",
    boardRing: "0 1px 2px #0000001f",
  },
  dark: {
    bg: "#101113",
    rail: "#101113",
    surface: "#18191c",
    raised: "#1f2024",
    subtle: "#1e1f23",
    hover: "#26282c",
    text: "#ebeae6",
    muted: "#a3a2a7",
    faint: "#6f6f75",
    border: "#2a2b30",
    borderStrong: "#3b3d43",
    accent: "#4c61ee",
    accentHover: "#5d71f5",
    accentText: "#97a5ff",
    onAccent: "#ffffff",
    accentSoft: "#1d2240",
    success: "#45c486",
    successSoft: "#14281e",
    warning: "#efac3a",
    warningSoft: "#2c2213",
    danger: "#ff7b6f",
    dangerSoft: "#33191a",
    board: "#0a0b0c",
    boardRaised: "#131417",
    boardLine: "#26282d",
    boardText: "#f2efe8",
    boardMuted: "#8a8d94",
    led: "#ffb224",
    ledGo: "#5fdc9b",
    ledStop: "#ff8a7f",
    cardRing: "0 0 0 1px #ffffff0b",
    boardRing: "0 0 0 1px #ffffff12",
  },
};
let boardTheme: ThemeConfig | null = null;
export function getBoardTheme(): ThemeConfig {
  if (boardTheme) return boardTheme;
  const base = getTheme(true).config;
  const p = palettes.dark;
  boardTheme = {
    ...base,
    token: {
      ...base.token,
      colorBgBase: p.board,
      colorBgContainer: p.boardRaised,
      colorText: p.boardText,
      colorTextSecondary: p.boardMuted,
    },
    components: {
      ...base.components,
      Button: {
        ...base.components?.Button,
        defaultBg: "#ffffff12",
        defaultColor: p.boardText,
        defaultBorderColor: "transparent",
        defaultShadow: "none",
        defaultHoverBg: "#ffffff1f",
        defaultHoverColor: p.boardText,
        defaultHoverBorderColor: "transparent",
        defaultActiveBg: "#ffffff29",
        defaultActiveColor: p.boardText,
        defaultActiveBorderColor: "transparent",
        textHoverBg: "#ffffff14",
        borderColorDisabled: "transparent",
        colorBgContainerDisabled: "#ffffff0a",
        colorTextDisabled: "#ffffff52",
      },
    },
  };
  return boardTheme;
}
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
        colorLink: p.accentText,
        colorLinkHover: p.accentHover,
        colorSuccess: p.success,
        colorWarning: p.warning,
        colorError: p.danger,
        colorBgBase: p.bg,
        colorBgLayout: p.bg,
        colorBgContainer: p.surface,
        colorBgElevated: p.raised,
        colorText: p.text,
        colorTextSecondary: p.muted,
        colorBorder: p.borderStrong,
        colorBorderSecondary: p.border,
        borderRadius: 8,
        borderRadiusLG: 12,
        borderRadiusSM: 6,
        controlHeight: 32,
        fontSize: 14,
        fontFamily,
        fontFamilyCode: monoFontFamily,
        motionDurationMid: "0.2s",
        motionEaseInOut: "cubic-bezier(0.2, 0.8, 0.2, 1)",
      },
      components: {
        Button: {
          primaryColor: p.onAccent,
          primaryShadow: "inset 0 1px 0 #ffffff26, 0 1px 2px #00000026",
          defaultShadow: "0 1px 2px #0000000a",
          defaultBg: p.raised,
          defaultBorderColor: p.border,
          defaultHoverBg: p.subtle,
          defaultHoverColor: p.text,
          defaultHoverBorderColor: p.borderStrong,
          defaultActiveBg: p.hover,
          defaultActiveColor: p.text,
          defaultActiveBorderColor: p.borderStrong,
          textHoverBg: p.hover,
          fontWeight: 500,
        },
        Switch: { colorPrimary: p.accent, colorPrimaryHover: p.accentHover },
        Drawer: { colorBgElevated: p.surface },
        Modal: { contentBg: p.raised, headerBg: p.raised, titleFontSize: 16 },
        Alert: { borderRadiusLG: 10 },
      },
    },
  };
}
