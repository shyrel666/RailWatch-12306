# Privacy

RailWatch 12306 is designed as a local desktop application. It opens official 12306 web pages in a user-controlled browser session and stores runtime data on the user's machine.

## Local Data

On Windows, runtime data is stored under:

```text
%LOCALAPPDATA%\railwatch-12306
```

Typical files include:

- `user_config.json`: trip setup and monitor preferences
- `ui_preferences.json`: Electron UI preferences such as theme
- `railwatch.log`: application events
- `chrome_profile_12306/`: Chrome cookies, session storage and cache
- `device_profile.json`: local browser support profile
- `station_codes_cache.json`: station code cache

## What RailWatch Does Not Do

- It does not upload cookies or session data.
- It does not collect analytics.
- It does not send user configuration to a third-party service.
- It does not store passwords in the repository.
- It does not send payment, identity or order data to project maintainers.

## User Responsibility

Do not publish runtime data or screenshots that expose identity, account, ticket, order, cookie or session information. When reporting bugs, prefer redacted text descriptions over screenshots.
