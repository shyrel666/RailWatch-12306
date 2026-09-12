# Changelog

## 0.3.7 - 2026-09-12

- 工具内弹窗去原生：清除本地数据、关闭浏览器、结束核对、自动提交启动等主进程确认，以及"新版本已下载、是否立即重启安装"提示，全部改为应用内跟随明亮/深色主题的对话框样式；确认闸门仍保留在主进程，渲染层只负责展示与回传选择。导出日志的系统"另存为"对话框与系统通知保持原生。
- 自动提交模式下，官方「请核对以下信息」确认弹窗出现后直接点击“确认”提交，不再做弹窗内二次回读核对：弹窗打开时乘客会在背景页和弹窗表格各被读一遍，核对必然失败并导致弹窗挂起等待人工确认，错失抢票窗口。点击“提交订单”前的完整回读核对保持不变。
- 同步 Electron、Python 与安装包版本为 0.3.7。

## 0.3.6 - 2026-09-12

- 修复安装版「环境检查」报 `No module named 'selenium.webdriver.chrome.options'`：selenium 4.44 起浏览器子模块改为运行时懒加载，PyInstaller 静态分析收集不到。打包时强制收集全部 selenium 子模块，并在构建期断言关键子模块已进入产物，缺失即构建失败。
- Python 运行时启动时提前解析 selenium 懒加载导入，环境缺失时直接给出真实原因，而不是等到检查环境或启动监控时才报错。
- 同步 Electron、Python 与安装包版本为 0.3.6。

## 0.3.5 - 2026-09-12

- 重构仪表盘、行程设置、监控和事件面板，新增跟随系统主题、可折叠设置与订单处理引导。
- 统一前后端查询策略，保留旧配置调优；按服务端 Retry-After 等待，拒绝迟到或失败响应对应的旧查询结果。
- 批量读取余票表格，修正席别匹配并支持纯数字等车次；订单按实际区间回读，支持带票价席别和座位偏好。
- 改善订单确认回执丢失后的核对、跨进程恢复互斥和人工结束本地核对；未知提交不自动重放。
- 修复浏览器关闭后的会话恢复和 Python 子进程重启；残留 Chrome 清理按完整配置目录参数精确匹配，避免路径模糊匹配误关其他窗口。
- 导出日志包含暂停期间的保留事件；订单回读差异只列出不匹配字段，并隐藏期望与实际乘客姓名。
- 同步 Electron、Python 与安装包版本为 0.3.5。真实账号下单与支付未在自动化验收中执行。
- 修复 PyInstaller 命令行打包遗漏查询策略 JSON 导致安装版启动失败的问题，发布流水线增加打包运行时启动与订单恢复检查。

## 0.3.2 - 2026-09-08

- 新增「关于」页面：品牌标识、版本号、检查更新与 GitHub 入口，隐藏顶部操作栏，保持极简。
- 项目链接：GitHub 仓库、发布与下载、问题反馈、更新日志和 MIT 许可证，均在系统默认浏览器中打开。
- 底部附运行环境（Electron／Chromium／Node.js）和一句使用边界说明。
- 新增受限的外部链接桥接：只允许打开 `https://github.com` 链接，其他协议、域名和非法输入一律拒绝。

## 0.3.1 - 2026-09-08

- 默认主题改为浅色：新安装和未保存过主题偏好的用户直接进入浅色界面，已保存的偏好仍然生效。
- 全新品牌标识：应用图标改为平面单色 R 字标，侧边栏品牌区改为几何小写字标 `railwatch 12306`，版本号移至底部状态栏。
- 桌面快捷方式、任务栏和安装包图标随本次安装包更新，替换旧版图标。

## 0.3.0 - 2026-09-08

- 新增结构化交易结果与订单证据校验，区分预订待支付、候补待支付、生效和兑现。
- 全部目标车次优先检查现票，明确售罄且确认无订单后立即进入候补路径，保留原乘车日期。
- 新增 SQLite 提交意图、跨进程互斥、重启恢复及“继续处理／核对订单”，禁止重放未知提交。
- 候补提交前精确回读车次、日期、区间、席别、乘客和官方截止时间选项。
- 配置版本提升至 2，使用完整北京时间起售时刻及单调时钟调度，增加防休眠与恢复暂停。
- 移除周期性整页刷新、提交前鼠标动作和浏览器指纹修改；外部通知异步执行。
- 固定已验证的 Selenium／requests 版本，最低 Python 版本调整为 3.10。
- 验证通过：Python 145 项、Electron 30 项、React 75 项、Chrome 离线回归 22 项，以及构建和打包运行时恢复测试。
- 真实账号提交与支付尚未验收；不保证抢票成功或候补兑现。详见 [验收记录](docs/transaction-reliability.md)。

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
- Timed (定时抢票) monitoring now creates the browser before the wait, keeps the query page prewarmed with from/to/date synced from the config during the prewarm window, and no longer depends on the browser restoring the previous query.
- Only allowlisted not-on-sale dialogs use short retries; unknown failures retain configured query timeouts and adaptive backoff. Login, verification, order and unknown blocking dialogs require human action.
- Non-timed monitoring opens the query page and syncs query params from the saved config on start, instead of relying on whatever page the browser was left on.
- Session keep-alive reads the result within the current bounded asynchronous call. Expiry or three inconclusive probes stop the task and require manual restart.
- Environment checks and browser startup now detect when the local ChromeDriver major version no longer matches the installed Chrome (Chrome auto-updates itself) and automatically download a matching ChromeDriver into the data directory before failing, so "检查环境" self-heals instead of reporting a session-not-created error.
- The `dev` and `electron` npm scripts now clear `NODE_OPTIONS` before launching Electron, so machines with a global `NODE_OPTIONS=--openssl-legacy-provider` (a common legacy-webpack workaround that Electron's bundled Node rejects with exit code 9) can still run the dev shell.

### Reliability improvements

- Freeze timed task targets before browser initialization, including midnight boundaries and late starts.
- Add per-run cancellation, browser ownership and sequenced status events; block restart until the previous worker exits.
- Share query transactions between analysis and monitoring, validate form fields, reject stale results and accept confirmed empty results.
- Validate calendar dates and filter execution ranges in Beijing time using a backend-provided presale policy.
- Display actual stations and the running configuration snapshot; drive countdowns from backend deadlines.
- Bound frontend log buffers and render variable-height event rows with virtualization.
- Add fault-combination unit tests, isolated Chrome page fixtures and packaged Electron smoke checks.
