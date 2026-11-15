import fs from "node:fs";
import path from "node:path";

export type ThemePreference = "system" | "light" | "dark";

export type Rect = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export type PersistedWindowState = {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  maximized?: boolean;
  theme?: ThemePreference;
};

export type ResolvedWindowLayout = {
  x?: number;
  y?: number;
  width: number;
  height: number;
  minWidth: number;
  minHeight: number;
  maximized: boolean;
};

export const DEFAULT_WINDOW_WIDTH = 1440;
export const DEFAULT_WINDOW_HEIGHT = 900;
export const MIN_WINDOW_WIDTH = 840;
export const MIN_WINDOW_HEIGHT = 580;

const LIGHT_BACKGROUND = "#f4f3ef";
const DARK_BACKGROUND = "#101113";
const MIN_DISPLAY_OVERLAP = 40;

export function normalizeThemePreference(value: unknown): ThemePreference {
  return value === "light" || value === "dark" ? value : "system";
}

/** Return the matching startup canvas color for the active or resolved theme. */
export function themeBackgroundColor(theme: ThemePreference, systemShouldUseDark: boolean): "#101113" | "#f4f3ef" {
  const dark = theme === "dark" || (theme === "system" && systemShouldUseDark);
  return dark ? DARK_BACKGROUND : LIGHT_BACKGROUND;
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isValidRect(rect: unknown): rect is Rect {
  return Boolean(
    rect &&
      typeof rect === "object" &&
      isFiniteNumber((rect as Rect).x) &&
      isFiniteNumber((rect as Rect).y) &&
      isFiniteNumber((rect as Rect).width) &&
      isFiniteNumber((rect as Rect).height) &&
      (rect as Rect).width > 0 &&
      (rect as Rect).height > 0,
  );
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), Math.max(min, max));
}

function intersectionArea(a: Rect, b: Rect): number {
  const overlapX = Math.max(0, Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x));
  const overlapY = Math.max(0, Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y));
  return overlapX * overlapY;
}

/** Pick the display whose workArea matches saved bounds, falling back to primaryWorkArea. */
export function pickTargetWorkArea(
  bounds: Partial<Rect> | undefined,
  displays: Rect[],
  primaryWorkArea: Rect,
): Rect {
  const candidates = displays.filter(isValidRect);
  if (!candidates.length || !bounds || !isFiniteNumber(bounds.x) || !isFiniteNumber(bounds.y)) {
    return primaryWorkArea;
  }
  const width = isFiniteNumber(bounds.width) && bounds.width > 0 ? bounds.width : MIN_WINDOW_WIDTH;
  const height = isFiniteNumber(bounds.height) && bounds.height > 0 ? bounds.height : MIN_WINDOW_HEIGHT;
  const target: Rect = { x: bounds.x, y: bounds.y, width, height };
  const centerX = bounds.x + width / 2;
  const centerY = bounds.y + height / 2;

  const centerMatch = candidates.find(
    (area) =>
      centerX >= area.x &&
      centerX <= area.x + area.width &&
      centerY >= area.y &&
      centerY <= area.y + area.height,
  );
  if (centerMatch) {
    return centerMatch;
  }

  let bestArea = primaryWorkArea;
  let bestScore = MIN_DISPLAY_OVERLAP * MIN_DISPLAY_OVERLAP - 1;
  for (const area of candidates) {
    const score = intersectionArea(target, area);
    if (score > bestScore) {
      bestScore = score;
      bestArea = area;
    }
  }
  return bestArea;
}

/** Compute bounded window size, position and adaptive minimum constraints for the current display(s). */
export function resolveWindowLayout(
  saved: PersistedWindowState | null | undefined,
  displays: Rect[],
  primaryWorkArea: Rect,
): ResolvedWindowLayout {
  const safePrimary: Rect = isValidRect(primaryWorkArea)
    ? primaryWorkArea
    : { x: 0, y: 0, width: DEFAULT_WINDOW_WIDTH, height: DEFAULT_WINDOW_HEIGHT };

  const targetArea = pickTargetWorkArea(
    saved ? { x: saved.x, y: saved.y, width: saved.width, height: saved.height } : undefined,
    displays,
    safePrimary,
  );

  const minWidth = Math.min(MIN_WINDOW_WIDTH, Math.max(320, Math.round(targetArea.width)));
  const minHeight = Math.min(MIN_WINDOW_HEIGHT, Math.max(240, Math.round(targetArea.height)));

  const hasSavedSize = Boolean(
    saved && isFiniteNumber(saved.width) && saved.width > 0 && isFiniteNumber(saved.height) && saved.height > 0,
  );
  const rawWidth = hasSavedSize
    ? Math.round(saved!.width!)
    : Math.min(DEFAULT_WINDOW_WIDTH, Math.round(targetArea.width * 0.92));
  const rawHeight = hasSavedSize
    ? Math.round(saved!.height!)
    : Math.min(DEFAULT_WINDOW_HEIGHT, Math.round(targetArea.height * 0.92));

  const width = clamp(rawWidth, minWidth, Math.max(minWidth, Math.round(targetArea.width)));
  const height = clamp(rawHeight, minHeight, Math.max(minHeight, Math.round(targetArea.height)));

  let x: number | undefined;
  let y: number | undefined;
  if (saved && isFiniteNumber(saved.x) && isFiniteNumber(saved.y)) {
    x = clamp(Math.round(saved.x), targetArea.x, targetArea.x + Math.max(0, Math.round(targetArea.width) - width));
    y = clamp(Math.round(saved.y), targetArea.y, targetArea.y + Math.max(0, Math.round(targetArea.height) - height));
  }

  return {
    x,
    y,
    width,
    height,
    minWidth,
    minHeight,
    maximized: Boolean(saved?.maximized),
  };
}

/** Read persisted window state synchronously for instant window creation; ignore missing/corrupt files. */
export function loadWindowState(filePath: string | null | undefined): PersistedWindowState {
  if (!filePath) return {};
  try {
    const raw = JSON.parse(fs.readFileSync(filePath, "utf8")) as Record<string, unknown>;
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
    const parsed: PersistedWindowState = {};
    if (isFiniteNumber(raw.x) && isFiniteNumber(raw.y)) {
      parsed.x = Math.round(raw.x);
      parsed.y = Math.round(raw.y);
    }
    if (isFiniteNumber(raw.width) && raw.width > 0 && isFiniteNumber(raw.height) && raw.height > 0) {
      parsed.width = Math.round(raw.width);
      parsed.height = Math.round(raw.height);
    }
    if (typeof raw.maximized === "boolean") {
      parsed.maximized = raw.maximized;
    }
    if (raw.theme === "system" || raw.theme === "light" || raw.theme === "dark") {
      parsed.theme = raw.theme;
    }
    return parsed;
  } catch {
    return {};
  }
}

/** Persist window bounds and cached theme preference without failing app exit on I/O errors. */
export function saveWindowStateSync(filePath: string | null | undefined, state: PersistedWindowState): void {
  if (!filePath) return;
  try {
    fs.mkdirSync(path.dirname(filePath), { recursive: true });
    fs.writeFileSync(filePath, JSON.stringify(state, null, 2), "utf8");
  } catch {
    /* Non-fatal: window bounds and theme cache are purely convenience metadata. */
  }
}
