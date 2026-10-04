import { expect, test } from "vitest";
import { getTheme } from "./theme";

function luminance(hex: string) {
  const values = [1, 3, 5]
    .map((index) => parseInt(hex.slice(index, index + 2), 16) / 255)
    .map((value) =>
      value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4,
    );
  return values[0] * 0.2126 + values[1] * 0.7152 + values[2] * 0.0722;
}
test.each([false, true])(
  "theme dark=%s maintains readable text on its surfaces",
  (dark) => {
    const { variables: colors } = getTheme(dark);
    for (const [foreground, background] of [
      ["text", "surface"],
      ["text", "bg"],
      ["muted", "surface"],
      ["muted", "bg"],
      ["muted", "raised"],
      ["muted", "subtle"],
      ["muted", "accent-soft"],
      ["accent-text", "surface"],
      ["accent-text", "bg"],
      ["accent-text", "accent-soft"],
      ["on-accent", "accent"],
      ["success", "surface"],
      ["success", "success-soft"],
      ["warning", "surface"],
      ["warning", "warning-soft"],
      ["danger", "surface"],
      ["danger", "danger-soft"],
      ["board-text", "board"],
      ["board-muted", "board"],
      ["board-muted", "board-raised"],
      ["led", "board"],
      ["led-go", "board"],
      ["led-stop", "board"],
    ]) {
      const [low, high] = [
        luminance(colors[`--${foreground}`]),
        luminance(colors[`--${background}`]),
      ].sort((a, b) => a - b);
      expect(
        (high + 0.05) / (low + 0.05),
        `${foreground} on ${background}`,
      ).toBeGreaterThanOrEqual(4.5);
    }
  },
);
test("status colors never reuse the action color", () => {
  for (const dark of [false, true]) {
    const { variables: colors } = getTheme(dark);
    for (const tone of ["--success", "--warning", "--danger"])
      expect(colors[tone]).not.toBe(colors["--accent"]);
  }
});
