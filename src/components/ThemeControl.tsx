import { createContext, useContext } from "react";
import { Monitor, Moon, Sun } from "lucide-react";
import { themeOptions, type ThemeMode } from "../lib/theme";
import type { ThemeOrigin } from "../lib/themeTransition";

export const ThemeContext = createContext<{
  mode: ThemeMode;
  disabled: boolean;
  onChange: (mode: ThemeMode, origin?: ThemeOrigin) => void;
}>({ mode: "system", disabled: false, onChange: () => undefined });

const themeIcons = { system: Monitor, light: Sun, dark: Moon };

// Every mode stays one click away; the raised segment shows the current one.
export function ThemeControl() {
  const { mode, disabled, onChange } = useContext(ThemeContext);
  return (
    <div className="theme-switch" role="radiogroup" aria-label="外观主题">
      {themeOptions.map((option) => {
        const Icon = themeIcons[option.value];
        return (
          <button
            aria-checked={mode === option.value}
            aria-label={option.label}
            className="theme-switch-option"
            data-mode={option.value}
            disabled={disabled}
            key={option.value}
            onClick={(event) => {
              const rect = event.currentTarget.getBoundingClientRect();
              onChange(option.value, { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 });
            }}
            role="radio"
            title={option.label}
            type="button"
          >
            <Icon size={15} aria-hidden="true" />
          </button>
        );
      })}
    </div>
  );
}
