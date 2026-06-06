# Security Policy

## Supported Versions

The `main` branch is the active development line. Security fixes should target the latest source state unless a release branch is created later.

## Reporting a Vulnerability

Please open a private report if the hosting platform supports it. If private reporting is not available, open an issue with minimal reproduction details and avoid posting secrets, cookies, tokens, screenshots of personal tickets, or Chrome profile contents.

Useful reports include:

- Steps to reproduce
- Impact and affected files
- Whether local user data, cookies, session state, or account safety is involved
- Suggested fix, if known

## Sensitive Data

Do not attach or commit:

- `chrome_profile_12306/`
- `user_config.json`
- `railwatch.log` or exported event logs
- Cookies, session storage, screenshots containing personal identity data
- Downloaded ChromeDriver binaries

RailWatch stores runtime data locally and should never upload 12306 cookies or sessions.
