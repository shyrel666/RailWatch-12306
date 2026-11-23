# Privacy

RailWatch 12306 is designed as a local desktop application. It opens official 12306 web pages in a user-controlled browser session and stores runtime data on the user's machine.

## Local Data

Runtime and desktop shell data are stored under one primary directory per platform:

```text
Windows: %LOCALAPPDATA%\railwatch-12306
macOS:   ~/Library/Application Support/railwatch-12306
Linux:   ${XDG_DATA_HOME:-~/.local/share}/railwatch-12306
```

Update packages downloaded by `electron-updater` are cached separately by the OS updater cache directory:

```text
Windows: %LOCALAPPDATA%\railwatch-12306-electron-updater
macOS:   ~/Library/Caches/railwatch-12306-electron-updater
Linux:   ${XDG_CACHE_HOME:-~/.cache}/railwatch-12306-electron-updater
```

(Earlier builds stored Electron's `userData` in the default OS app-data folder such as `%APPDATA%\railwatch-12306-electron` on Windows or `~/Library/Application Support/railwatch-12306-electron` on macOS; `window-state.json` and `.updaterId` are automatically migrated into `electron/` inside the primary directory on startup.)

Typical files and subdirectories under `railwatch-12306/` include:

- `user_config.json`: trip setup and monitor preferences
- `trip_draft.json`: recoverable trip edits, which can include passenger names
- `trip_presets.json` stores saved trip presets in the data directory root and can include passenger names and selections.
- `trip_choices.json`: recent station pairs and route-specific train favorites
- `ui_preferences.json`: Electron UI preferences such as theme
- `notification_settings.json` stores notification channel settings. Credential storage depends on the operating system.
- `orders.sqlite3`: order intents, status evidence and event history, which can include passenger names and trip details
- `railwatch.log`: application events
- `chrome_profile_12306/`: Chrome cookies, session storage and cache
- `notification-sounds/`: user-imported custom alert audio files
- `device_profile.json`: local browser support profile
- `station_codes_cache.json`: station code cache
- `electron/`: Electron `userData` directory containing `window-state.json`, `.updaterId`, and Chromium renderer cache/storage

The renderer also stores UI cache keys (`railwatch.theme` and `railwatch.sidebarCollapsed`) in `localStorage`.

### Trip Backups

An export writes trip presets, route favorites, and recent routes to a JSON file at the location you choose. The exporter removes passenger names and selections from trip preset configuration and excludes browser cookies, 12306 login and session data, order records, and all notification settings and credentials.

An import merges presets and route choices. RailWatch discards any passenger names and selections in an imported preset and sets automatic submission and automatic waitlisting to off. Starting monitoring requires a separate user action after importing or loading a preset.

### Clearing Local Data and Uninstalling

- **In-app reset ("清除数据", confirmed with "清除本地数据")** stops the controlled Chrome session and removes runtime data under `railwatch-12306/`, including `trip_presets.json`. It clears Electron `window-state.json`, Chromium session storage and cache, and `railwatch.*` `localStorage` keys while keeping live Chromium handles under `electron/` stable. It also removes the `railwatch-12306-electron-updater` package cache and the macOS notification credentials item. RailWatch reports failures to remove files or the keychain item.
- **Windows uninstaller**: manual uninstall presents an opt-in checkbox ("同时删除本地配置、12306 登录数据与更新缓存", also selectable via `--delete-app-data`) to remove `%LOCALAPPDATA%\railwatch-12306`, `%LOCALAPPDATA%\railwatch-12306-electron-updater`, and legacy `%APPDATA%\railwatch-12306-electron`. Automatic in-place updates (`--updated`) always preserve local data.

## External Notifications

When you configure and enable a channel, RailWatch can send a fixed test message or alerts for the events you select. The receiving service gets the alert content and RailWatch shows the send result locally. Supported channels include email, Server 酱, WeCom, Bark, ntfy, DingTalk, Feishu, PushPlus, and custom Webhooks. HTTP-based channels use HTTPS and reject redirects. Email uses STARTTLS on port 587 and SMTP over TLS on other configured ports.

DingTalk and Feishu Webhook URLs and signing secrets, the PushPlus token, and the custom Webhook URL and bearer token use the same storage as existing notification credentials.

- Windows encrypts credentials in `notification_settings.json` using the current user's DPAPI protection.
- macOS stores credentials in one login-keychain item (`org.railwatch.railwatch12306` / `notification-secrets`) and writes credential markers to `notification_settings.json`.
- Linux stores credentials in `notification_settings.json` as plaintext.

## Other Network Requests

Browsing and transactions contact the official 12306 site through your local Chrome session.

The dashboard sale calendar reads the public station sale-time table from `kyfw.12306.cn` over HTTPS. Station matching happens locally; this request does not send the configured trip, passenger details or browser cookies. The table is cached in process memory for up to one hour. Refresh attempts are spaced at least one minute apart, and no cache file is written.

When you download ChromeDriver automatically (from Settings or during environment setup), RailWatch prioritizes the third-party `npmmirror` mirror (`registry.npmmirror.com` and `cdn.npmmirror.com`) over HTTPS so users in mainland China can download without direct access to Google hosts, and falls back to official Chrome for Testing / Google Storage endpoints (`googlechromelabs.github.io`, `storage.googleapis.com`, `chromedriver.storage.googleapis.com`) only if the mirror fails. Only Chrome major-version and OS architecture metadata is sent in those requests; no 12306 account data, cookies or trip configuration is shared.

## What RailWatch Does Not Do

- It does not upload cookies or session data.
- It does not collect analytics.
- It does not send the full user configuration to project maintainers.
- It does not store passwords in the repository.
- It does not send payment, identity or order data to project maintainers.

## User Responsibility

Do not publish runtime data or screenshots that expose identity, account, ticket, order, cookie or session information. When reporting bugs, prefer redacted text descriptions over screenshots.
