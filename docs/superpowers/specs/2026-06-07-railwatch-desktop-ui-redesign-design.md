# RailWatch Desktop UI Redesign Design

Date: 2026-06-07

## Summary

Redesign the RailWatch 12306 Electron desktop UI as a premium macOS-style dark desktop tool. The redesign keeps the existing Electron + React + Ant Design architecture and preserves the current product boundaries: Dashboard, Trip Setup, Monitor, Settings, and Event Panel.

The confirmed visual direction is page-specific:

- Dashboard uses the "Rail Dispatch Darkroom" direction: a deep, professional train-dispatch dashboard with workflow status, route context, monitoring readiness, and risk signals.
- Trip Setup uses the "Quiet Safety Desk" direction: a calm, low-error form workspace for route, train, passenger, polling, timer, and automation settings.
- These pages must not be merged into a single combined workspace. They share a theme and interaction language, but each page has its own layout and job.

## Goals

- Make the app feel like a polished macOS desktop utility rather than a generic web admin panel.
- Make dark mode feel designed as a first-class primary theme.
- Improve information clarity for status, readiness, events, and risk.
- Make repeated workflows faster: configure trip, analyze query, start monitoring, review events.
- Lower the chance of dangerous accidental actions, especially automatic submit, automatic alternate, close browser, and clear local data.

## Non-Goals

- Do not change the 12306 query or monitoring core behavior.
- Do not add automatic purchase, automatic payment, captcha bypass, or hidden automation.
- Do not change the Python runtime command contract unless a UI change exposes an existing field more clearly.
- Do not turn the app into a landing page or marketing screen.
- Do not use the generated visual exploration images as runtime assets.

## Design Principles

- Dense but calm: RailWatch is an operational tool, so pages should scan quickly without visual noise.
- macOS-like polish: use restrained translucency, crisp typography, subtle borders, and careful elevation.
- Safety before speed: high-risk operations are visible, isolated, and confirmed.
- Page boundaries stay obvious: Dashboard shows the system state; Trip Setup edits configuration; Monitor controls running work; Settings handles environment and preferences.
- Real controls over explanatory text: use buttons, icon buttons with tooltips, switches, steppers, segmented controls, filters, and drawers where they fit.

## Shared Theme

The redesign should introduce a stronger theme layer through CSS variables and Ant Design tokens.

### Dark Theme

Dark mode is the primary visual target.

- Background: deep charcoal, not pure black.
- Primary surfaces: layered graphite with subtle translucency.
- Elevated surfaces: slightly lighter graphite with low-contrast borders.
- Text: high-contrast off-white for primary text, blue-gray for secondary text.
- Primary accent: blue-green/cyan for active monitoring and workflow progress.
- Success: clean rail green.
- Warning: warm amber for risk and confirmation states.
- Danger: restrained red, reserved for destructive or unsafe operations.

### Light Theme

Light mode remains supported but should be quieter.

- Background: cool neutral gray.
- Surfaces: soft white and pale graphite tints.
- Accent and risk colors match dark mode semantics.
- Layout and interaction states must remain identical to dark mode.

### Component Tokens

- Border radius: mostly 8px or less for controls and repeated items; slightly larger only for main shell surfaces.
- Focus state: visible 2px accent ring or glow that does not shift layout.
- Buttons: icon buttons for event tools and compact commands; icon+text buttons for primary workflow commands.
- Inputs: stable height, clear focus, consistent dark/light styling for native date and time inputs.
- Tables: calm row separators, compact density, no nested card appearance.

## Shell Layout

The app keeps the three-zone desktop structure:

- Left sidebar: app identity, four primary pages, data directory summary.
- Main workspace: current page content with a compact topbar.
- Event panel: right-side drawer/panel that can be shown or hidden.

The shell should feel more desktop-native:

- Sidebar uses a darker translucent rail with clear active selection.
- Topbar uses a compact status command row instead of a page-header-heavy web layout.
- Event panel remains available from all pages and keeps filter, pause, clear, and export controls.
- The event panel can appear as a fixed right panel on wide viewports and collapse on narrower desktop widths.

## Dashboard Page

Dashboard adopts the Rail Dispatch Darkroom direction.

### Purpose

Dashboard is the operational overview. It should answer:

- Is the environment ready?
- Is login ready?
- Has query analysis completed?
- Is monitoring running?
- Was a target ticket hit?
- Are any risky automation options enabled?

### Layout

Use a dispatch-style structure:

- Route/status command strip near the top with current status summary and page-level actions.
- Workflow stepper for environment, login, query, monitor, and hit.
- Metric/status panels for environment, login, query, monitoring, hits, and risk.
- Recent hits table as a single grouped surface with lightweight row separation.
- Risk panel or badge that becomes visually stronger only when unsafe automation is enabled.

Dashboard must not include the full Trip Setup form. It may show a compact route summary derived from current config, but editing stays on Trip Setup.

### Interactions

- Workflow steps should reflect current status and risk level from the store.
- Event panel toggle remains accessible from the topbar.
- Status panels can stay non-clickable in the first implementation unless an existing navigation action is obvious.
- Empty states should be calm and specific, not generic.

## Trip Setup Page

Trip Setup adopts the Quiet Safety Desk direction.

### Purpose

Trip Setup is the configuration workspace. It should make route setup feel deliberate and safe.

### Layout

Use a calm two-column form layout:

- Main form area: route, date, train, seat, passenger, interval, passenger count, seat preference, prepare time, target time.
- Safety/review area: timer, keep-alive, smart polling, automatic submit, automatic alternate, alternate deadline.
- Bottom action row: Save as secondary action, Analyze as primary action.

The page should not adopt the Dashboard's dispatch workflow timeline. It can use the same theme, status colors, and surface language, but the structure remains form-first.

### Interactions

- Inputs have strong focus states.
- Numeric settings use steppers or Ant Design InputNumber with consistent compact styling.
- Binary settings use switches with labels and short descriptions where needed.
- Dangerous automation toggles are grouped in a visible safety section.
- Enabling automatic submit or automatic alternate keeps the current confirmation flow.
- Save and Analyze buttons expose loading states and cannot shift layout.

## Monitor Page

Monitor should sit between the two selected directions:

- It inherits the Dashboard's operational tone for start/stop and live state.
- It uses the Trip Setup's calm density for query results.

Expected structure:

- Monitoring control band with Start Monitor and Stop Monitor.
- Current summary/status callout.
- Query results table with compact density.
- Clear disabled states when query is not ready or monitoring is already running.

## Settings Page

Settings should use the Quiet Safety Desk tone:

- Appearance section with dark mode switch.
- Data section with data directory, ChromeDriver path, and Chrome version.
- Control section with environment check, ChromeDriver download, login, close browser, and clear data actions.

Dangerous actions, especially close browser and clear local data, should be visually separated from neutral environment actions.

## Event Panel

The event panel remains a cross-page tool.

Required controls:

- Severity filter.
- Pause/resume auto-scroll.
- Clear events.
- Export events.

Visual behavior:

- Use compact rows with left severity markers.
- Error and warning rows should be visible without making the panel noisy.
- Empty and paused states should be clear.
- Tool buttons should be icon-first with tooltips.

## Safety And Confirmation

The redesign must keep existing safety behavior:

- Automatic submit requires confirmation before enabling.
- Automatic alternate requires confirmation before enabling.
- Runtime commands that return confirmation requests must still use the modal confirmation path.
- Destructive settings actions should remain visually distinct and should not become more casual through styling.

The UI should make unsafe automation easy to notice and hard to enable by accident.

## Implementation Shape

Prefer a scoped renderer refactor:

- Centralize theme variables in `src/styles.css`.
- Extend Ant Design token configuration in `src/App.tsx` and remove duplicate provider drift where practical.
- Keep shared primitives in `src/components/DisplayPrimitives.tsx` and `src/components/FormPrimitives.tsx`.
- Update `Shell.tsx`, `DashboardPage.tsx`, `TripSetupPage.tsx`, `MonitorPage.tsx`, `SettingsPage.tsx`, and `EventPanel.tsx`.
- Avoid touching Electron main, preload, Python runtime, and Selenium core for this UI-only redesign.

## Testing And Verification

Automated checks:

- `npm run typecheck`
- `npm run test:renderer`
- Existing component tests should be updated only when accessible labels, text, or structure intentionally changes.

Visual/manual checks:

- Dashboard shows the dispatch-style state overview and does not contain Trip Setup's full form.
- Trip Setup shows the quiet form workspace and does not contain the Dashboard workflow timeline.
- Event panel can be hidden and shown.
- Dark mode and light mode both preserve readable contrast.
- Dangerous automation toggles still trigger confirmation.
- Buttons, inputs, switches, filters, and tables do not resize unexpectedly during loading or state changes.

## Open Decisions

No product decisions are unresolved. The approved direction is:

- Dashboard: option 2, Rail Dispatch Darkroom.
- Trip Setup: option 3, Quiet Safety Desk.
- Shared shell/theme: macOS-style premium dark desktop tool.
