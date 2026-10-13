// Let the 900ms track drawing and 380ms signal illumination finish before fading.
const minimumVisibleMs = 1300;
const fadeMs = 220;
const maximumWaitMs = 10000;

let finishSplash = () => {};

/** Start once per document, independently of React's StrictMode effects. */
export function initializeStartupSplash(): void {
  const splash = document.getElementById("startup-splash");
  const root = document.getElementById("root");
  if (!splash || !root) return;

  let startedAt: number | null = null;
  let ready = false;
  let finishing = false;
  const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const dismiss = () => {
    root.removeAttribute("inert");
    splash.setAttribute("aria-hidden", "true");
    splash.classList.add("startup-splash-leaving");
    window.setTimeout(() => splash.remove(), reducedMotion() ? 0 : fadeMs);
  };
  const startAnimation = () => {
    if (startedAt !== null) return;
    startedAt = performance.now();
    splash.classList.add("startup-splash-running");
    if (ready) finishSplash();
  };
  const fallback = window.setTimeout(() => {
    // Also recover if the window notification or runtime initialization is lost.
    startAnimation();
    finishSplash();
  }, maximumWaitMs);
  finishSplash = () => {
    ready = true;
    if (finishing || startedAt === null) return;
    finishing = true;
    window.clearTimeout(fallback);
    const remaining = reducedMotion() ? 0 : Math.max(0, minimumVisibleMs - (performance.now() - startedAt));
    window.setTimeout(dismiss, remaining);
  };
  if (window.railwatch?.whenWindowShown) {
    void window.railwatch.whenWindowShown().then(startAnimation, startAnimation);
  } else {
    startAnimation();
  }
}

/** Also called on initialization failure so existing error/retry controls remain accessible. */
export function finishStartupSplash(): void {
  finishSplash();
}
