export type ThemeOrigin = { x: number; y: number };

// Animate a single captured layer, not every live component's color/background.
export async function transitionTheme(update: () => void, origin?: ThemeOrigin): Promise<void> {
  if (!document.startViewTransition || document.hidden
      || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    update();
    return;
  }
  const root = document.documentElement;
  const x = Math.max(0, Math.min(window.innerWidth, origin?.x ?? window.innerWidth - 80));
  const y = Math.max(0, Math.min(window.innerHeight, origin?.y ?? 40));
  const radius = Math.ceil(Math.hypot(Math.max(x, window.innerWidth - x), Math.max(y, window.innerHeight - y)));
  let applied = false;
  const apply = () => {
    if (!applied) {
      applied = true;
      update();
    }
  };
  let transition: ViewTransition | undefined;
  root.dataset.themeTransition = "active";
  try {
    transition = document.startViewTransition(apply);
    // Observe rejection immediately: hidden windows or unsupported snapshots can skip the animation.
    const finished = transition.finished.catch(() => undefined);
    await transition.ready;
    const animation = root.animate({ clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${radius}px at ${x}px ${y}px)`] }, {
      duration: 420,
      easing: "cubic-bezier(0.22, 1, 0.36, 1)",
      pseudoElement: "::view-transition-new(root)",
      fill: "both",
    });
    try {
      await animation.finished;
    } finally {
      animation.cancel();
    }
    await finished;
  } catch {
    transition?.skipTransition();
    // Skipping a transition can still schedule its update callback. Apply at most once.
    apply();
  } finally {
    delete root.dataset.themeTransition;
  }
}
