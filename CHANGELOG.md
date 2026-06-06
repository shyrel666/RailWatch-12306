# Changelog

## 0.1.0 - Unreleased

### Added

- Introduced the RailWatch 12306 product name and open-source project framing.
- Added a PySide6 desktop operations console with Dashboard, Trip Setup, Monitor and Settings pages.
- Added `RailWatchState` as the UI-facing state model for environment, login, query, monitor, hit, alternate and error states.
- Added event log filtering and export controls.
- Added safety confirmations for auto submit, auto alternate, browser close and local data clearing.
- Added open-source docs for contributing, security, privacy and release readiness.

### Changed

- Updated the default local data directory to `railwatch-12306`.
- Updated build output naming to `RailWatch 12306`.
- Kept the legacy Tkinter UI as a fallback behind the PySide6 entry point.

### Removed

- Removed local runtime data, generated build output and downloaded ChromeDriver binary from the working tree.
