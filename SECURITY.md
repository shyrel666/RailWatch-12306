# Security Policy

RailWatch 12306 is a local desktop application. Security issues usually involve local data handling, browser session safety, packaged executable behavior, or unsafe automation around official 12306 pages.

## Supported Versions

The `main` branch is the active development line until release branches are created. Security fixes should target the latest source state.

## Reporting A Vulnerability

Use GitHub private vulnerability reporting if available. If private reporting is not enabled, open an issue with minimal reproduction details and do not include secrets or personal data.

Useful reports include:

- Affected version or commit
- Operating system
- Steps to reproduce
- Impact and affected files
- Whether Chrome profile data, cookies, local config, logs or account safety are involved
- Suggested fix, if known

## Sensitive Data

Do not attach or commit:

- `chrome_profile_12306/`
- `user_config.json`
- `ui_preferences.json`
- `railwatch.log` or exported event logs
- Cookies, session storage or browser profile contents
- Screenshots containing identity, account, ticket or order information
- Downloaded ChromeDriver binaries

RailWatch should never upload 12306 cookies, sessions, passwords or local user configuration.

## Security Boundaries

- RailWatch does not crack captchas or bypass login verification.
- RailWatch does not call private 12306 APIs.
- RailWatch does not complete payment for the user.
- Electron renderer code must access native capabilities only through the preload allowlist.
- Python runtime commands must keep destructive actions confirmation-gated.
