import { createContext, useContext } from "react";
import { Button } from "antd";
import { Monitor, Moon, Sun } from "lucide-react";
import { themeOptions, type ThemeMode } from "../lib/theme";

export const ThemeContext = createContext<{
  mode: ThemeMode;
  disabled: boolean;
  onChange: (mode: ThemeMode) => void;
}>({ mode: "system", disabled: false, onChange: () => undefined });
export function ThemeControl() {
  const { mode, disabled, onChange } = useContext(ThemeContext);
  const currentIndex = themeOptions.findIndex((option) => option.value === mode);
  const current = themeOptions[currentIndex];
  const next = themeOptions[(currentIndex + 1) % themeOptions.length];
  const Icon = mode === "system" ? Monitor : mode === "light" ? Sun : Moon;
  return (
    <Button
      aria-label={`外观主题：${current.label}，点击切换为${next.label}`}
      title={`切换为${next.label}`}
      className="theme-toggle"
      icon={<Icon size={16} aria-hidden="true" />}
      disabled={disabled}
      onClick={() => onChange(next.value)}
    >
      {current.label}
    </Button>
  );
}
