import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { railwatchApi } from "./railwatchApi";
import type { PreferencesPatch, RailWatchPreferences } from "../types";
import { getTheme, normalizeTheme, type ThemeMode } from "./theme";
import { transitionTheme, type ThemeOrigin } from "./themeTransition";

const cacheKey = "railwatch.theme";
function cachedTheme() {
  try {
    return normalizeTheme(localStorage.getItem(cacheKey));
  } catch {
    return "system" as const;
  }
}
function cacheTheme(mode: ThemeMode) {
  try {
    localStorage.setItem(cacheKey, mode);
  } catch {
    /* Preferences file remains authoritative. */
  }
}

export function useThemePreference() {
  const [mode, setMode] = useState<ThemeMode>(cachedTheme);
  const [systemDark, setSystemDark] = useState(
    () => window.matchMedia("(prefers-color-scheme: dark)").matches,
  );
  const [ready, setReady] = useState(false);
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);
  const darkMode = mode === "dark" || (mode === "system" && systemDark);
  const design = useMemo(() => getTheme(darkMode), [darkMode]);
  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const update = () => setSystemDark(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  useEffect(() => {
    let alive = true;
    void railwatchApi
      .command<RailWatchPreferences>("loadPreferences")
      .then((value) => {
        if (alive) {
          const next = normalizeTheme(value?.theme);
          setMode(next);
          cacheTheme(next);
        }
      })
      .catch(() => undefined)
      .finally(() => {
        if (alive) setReady(true);
      });
    return () => {
      alive = false;
    };
  }, []);
  useLayoutEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = darkMode ? "dark" : "light";
    root.style.colorScheme = darkMode ? "dark" : "light";
    for (const [name, value] of Object.entries(design.variables))
      root.style.setProperty(name, value);
  }, [darkMode, design]);
  async function saveTheme(next: ThemeMode, origin?: ThemeOrigin) {
    if (!ready || savingRef.current || next === mode) return;
    const previous = mode;
    savingRef.current = true;
    setSaving(true);
    try {
      const nextDark = next === "dark" || (next === "system" && systemDark);
      if (nextDark !== darkMode) {
        await transitionTheme(() => flushSync(() => setMode(next)), origin);
      } else {
        setMode(next);
      }
      const patch: PreferencesPatch = { theme: next };
      const result = await railwatchApi.command<RailWatchPreferences>(
        "savePreferences",
        patch,
      );
      const saved = normalizeTheme(result?.theme);
      if (saved !== next) throw new Error("主题偏好未保存，请重试。");
      cacheTheme(saved);
    } catch (error) {
      setMode(previous);
      throw error;
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }
  return { mode, darkMode, design, saveTheme, disabled: !ready || saving };
}
