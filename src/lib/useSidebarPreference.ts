import { useEffect, useState } from "react";

const key = "railwatch.sidebarCollapsed";
function storedPreference(): boolean | null {
  try {
    const value = localStorage.getItem(key);
    return value === "true" ? true : value === "false" ? false : null;
  } catch {
    return null;
  }
}

export function useSidebarPreference() {
  const [preference, setPreference] = useState(storedPreference);
  const [compact, setCompact] = useState(() => window.matchMedia("(max-width: 1279px)").matches);
  useEffect(() => {
    const media = window.matchMedia("(max-width: 1279px)");
    const update = () => setCompact(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  const collapsed = preference ?? compact;
  const toggle = () => {
    const next = !collapsed;
    setPreference(next);
    try {
      localStorage.setItem(key, String(next));
    } catch {
      // Keep this session usable if local storage is unavailable.
    }
  };
  return { collapsed, toggle };
}
