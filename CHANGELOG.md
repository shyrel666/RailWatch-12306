# Changelog

## 0.1.0 - Unreleased

### Added

- Added the Electron + React/Vite desktop shell.
- Added the JSON Lines Python runtime used by Electron.
- Added `RailWatchBridge` as the frontend-neutral command facade for runtime info, config, environment checks, login, query analysis, monitoring, logging and preferences.
- Added renderer state management and component tests for navigation, trip setup and monitor controls.
- Added Windows Electron packaging with `electron-builder` and PyInstaller runtime bundling.
- Added open-source GitHub docs, issue templates, PR template, CI workflow and release QA checklist.

### Changed

- Repositioned Python code as runtime/core support for the Electron app.
- Updated source hygiene rules to keep runtime data, logs, Chrome profiles, downloaded drivers and build output out of Git.
- Updated Vite build splitting for stable React, icon and vendor chunks.
