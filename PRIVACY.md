# Privacy

RailWatch 12306 is designed as a local desktop application. It uses the official 12306 web pages through a user-controlled browser session and stores runtime data on the user's machine.

## Local Data

By default, runtime data is stored outside the source directory:

```text
%LOCALAPPDATA%\railwatch-12306
```

Typical files include:

- `user_config.json`: trip setup and monitor preferences
- `railwatch.log`: application events
- `chrome_profile_12306/`: Chrome cookies, session storage and cache
- `device_profile.json`: local browser support profile
- `station_codes_cache.json`: station code cache

## What RailWatch Does Not Do

- It does not upload cookies or session data.
- It does not collect analytics.
- It does not send user configuration to a third-party service.
- It does not store passwords in source files.

## User Responsibility

Do not commit runtime data or screenshots that expose personal identity, order, ticket, cookie or session information.
