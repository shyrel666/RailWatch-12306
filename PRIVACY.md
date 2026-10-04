# Privacy

RailWatch 12306 is designed as a local desktop application. It opens official 12306 web pages in a user-controlled browser session and stores runtime data on the user's machine.

## Local Data

Runtime data is stored under:

```text
Windows: %LOCALAPPDATA%\railwatch-12306
macOS:   ~/Library/Application Support/railwatch-12306
```

Typical files include:

- `user_config.json`: trip setup and monitor preferences
- `trip_draft.json`: recoverable trip edits, which can include passenger names
- `trip_choices.json`: recent station pairs and route-specific train favorites
- `ui_preferences.json`: Electron UI preferences such as theme
- `notification_settings.json`: notification channel settings; Windows secrets use the current user's DPAPI protection, while macOS keeps them in one login-keychain item (`org.railwatch.railwatch12306` / `notification-secrets`) and the file only records which fields are set. Clearing local data also deletes that keychain item.
- `orders.sqlite3`: order intents, status evidence and event history, which can include passenger names and trip details
- `railwatch.log`: application events
- `chrome_profile_12306/`: Chrome cookies, session storage and cache
- `device_profile.json`: local browser support profile
- `station_codes_cache.json`: station code cache

The app can send a test message or a selected order/ticket alert through email, Server 酱 or WeCom when you configure and enable that channel. Those services receive the alert content; the app shows the result locally. Browsing and transactions also contact the official 12306 site through your local Chrome session.

The dashboard sale calendar reads the public station sale-time table from `kyfw.12306.cn` over HTTPS. Station matching happens locally; this request does not send the configured trip, passenger details or browser cookies. The table is cached in process memory for up to one hour. Refresh attempts are spaced at least one minute apart, and no cache file is written.

The renderer also stores the theme cache and the user's sidebar collapse choice in local browser storage on this machine.

## What RailWatch Does Not Do

- It does not upload cookies or session data.
- It does not collect analytics.
- It does not send the full user configuration to project maintainers.
- It does not store passwords in the repository.
- It does not send payment, identity or order data to project maintainers.

## User Responsibility

Do not publish runtime data or screenshots that expose identity, account, ticket, order, cookie or session information. When reporting bugs, prefer redacted text descriptions over screenshots.
