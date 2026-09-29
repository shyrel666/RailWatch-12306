# Changelog

## 0.5.0 - 2026-09-29

- 新增起售彩排：只读检查配置、官方起售时刻、浏览器、登录、乘车人、车次席别、时钟、唤醒与提醒渠道；支持取消、修复入口、报告过期提示和最近 20 次报告。
- 按官方乘车人页实测结构读取身份核验与类型，跨页查重；本人未显示票种保持未知，“预通过”等证件例外不误判为官方禁止购票。
- 普通订单与候补只在本地断网页面演练，标签页离线、网络封锁、地址和句柄守卫共同隔离；结束或取消恢复原标签页，不写交易记录。
- 新增预测时间线与起售复盘，区分本机实测、历史中位数、本地脚本和未知；遥测清理后不推测补齐首次查询。
- 自动彩排默认关闭，可在设置开启；仅在定时任务距起售超过 15 分钟时运行。手动彩排受浏览器互斥、未决订单、两分钟冷却和起售前五分钟限制。
- 支持清除本地彩排报告，保留订单与实战复盘；运行中禁止清理，清理后仍保留冷却限制。
- 候补截止支持常用时间下拉选择，并保留完整日期时间输入；提交时仍核对官方页面选项。
- 延长运行时启动就绪等待，避免冷启动与网络检查超过十秒时误杀正常进程；无响应仍会超时恢复。
- 验证证据与尚未完成的真实账号验收见 `docs/v0.5.0-validation.md`。

## 0.4.2 - 2026-09-28

- 修复确认点击回执未知时的重复提交与离页风险；提交后的空订单列表不再解除未决订单保护，售罄回退要求明确的提交前失败证据。
- 查询快照失效时有界重取，持续失效明确提示；合并浏览器状态读取，减少轮询调用，保留核验检查。
- 启动摘要统一由主进程发起，忽略调用方确认标记，确认期间配置变化拒绝启动；运行时增加有限退避、就绪握手和手动恢复，隔离坏协议行。
- 人工动作提示可随状态恢复，订单观察设置退避和预算；区分历史证据缺失与显示截断，日志统一记录完整北京时间。
- 补齐 Python 起售时间模块打包声明，完善页面加载失败恢复，清理无用更新下载与兼容代码；更新 README 三张界面截图。

- 优化订单历史分页：新增排序、状态筛选及官方证据索引，深页按复合游标直接定位；每页摘要批量读取，20 条列表从 61 次 SELECT 降为 2 次，保留官方证据、最近核对和旧数据语义。
- 修复多渠道通知部分入队后错误阻止其余渠道重试的问题；按事件与渠道去重，队列满可见，旧发送结果不再覆盖较新的排队失败状态。
- 通知改用每渠道独立工作线程与有界队列，防止慢渠道阻塞其他渠道；试发共用等待截止时间，未完成发送显示为排队中。
- 安装更新前释放受控浏览器和 ChromeDriver，清理失败或超时不返回就绪；超时后的清理期间继续阻止新浏览器任务进入。
- 收藏与查询共用车次格式规则，支持 1461 等纯数字车次，保存和重新读取时保持顺序、去重并规范大小写。
- 订单页面核对时间独立于订单状态变化，记录相同状态、未知结果与读取失败；合并持久化最近核对结果，观察期间订单中心定期刷新，保留最后确认的官方证据。
- 修复查询余票（包括查询全部车次）隐式覆盖正式配置的问题，查询成功或失败均保留已保存行程及可恢复草稿。
- 修复运行任务结果向下一次草稿添加车次时使用旧路线和旧优先级的问题；按当前草稿校验区间、日期并合并车次，条件变化后清除旧勾选。
- 修复运行时无法启动或停止超时导致正常入口无法退出的问题；提供默认取消的强制退出确认，保留已落库订单，阻止运行时重启，并在 Windows 上仅清理本应用当前运行时的进程树。
- 修复订单证据只保留首个车次的问题：合并所有可见结构化车次及页面文字证据，拒绝多车次或字段冲突，同时保持纯数字车次与票价的区分。
- 修复 Windows DPAPI 加解密失败导致运行时无法启动的问题；通知凭据损坏或旧明文迁移失败时保留原文件、告警并禁用外部通知，未完成订单仍可恢复。
- 修复原子写入异常清理时重复关闭文件描述符的问题，避免误关其他线程复用的文件；补充订单页面、凭据异常、文件写入故障及打包运行时回归测试。

- 完成 v0.4.2 M0：偏好支持局部更新，通知修改不再重置主题，读改写与活动设置更新统一加锁；定义查询、任务、草稿和订单公共契约，补充草稿只读校验、旧配置及并发保存回归。
- 完成 v0.4.2 M1：手动查询和监控复用结构化席别快照，按日期展示实际区间、时刻、选中席别、数字余票及候补状态，原始文字仅供展开查看；显示当前查询日期、最后成功时间及等待／过期／停止状态。
- 查询失败保留各日期上次成功结果，成功空结果仅清除对应日期；过滤旧任务、旧条件及迟到查询响应，补充 DOM 失效、离线浏览器和明暗主题界面回归。
- 完成 v0.4.2 M2：可配置关闭到托盘，显示运行状态、停止与退出入口；退出和安装更新通过后端锁内门禁与停止收尾，未完成订单保留，运行时状态不明时拒绝自动安装。
- 完成 v0.4.2 M3：桌面、循环声音、置顶及三种外部渠道设置实际生效；支持按事件选择渠道、保存后试发、结果与最近发送时间展示，并对外部发送设置并发上限、去重和脱敏反馈。
- 完成 v0.4.2 M4：站名联想、离线缓存、最近路线及路线收藏；从当前查询结果选择车次并调整优先级，席别按查询和交易能力展示，乘客票种与官方页面回读受严格校验。
- 行程编辑草稿独立原子保存、重启后可恢复，正式保存状态与运行任务快照分开；启动前核对实际日期、路线、车次、席别、乘客和自动化开关。
- 完成 v0.4.2 M5：订单中心提供历史分页、只读事件时间线、官方状态与本地核对状态、原订单继续核对入口；缺失的旧事件明确标为不完整，关键订单结果即时入库。

## 0.4.1 - 2026-09-21

- 修复纯数字车次可能被订单金额误识别的问题；只有结构化车次字段或带“次”的明确车次标记才可作为纯数字车次证据。
- 修复周期性运行时信息响应晚于状态事件时回滚监控状态的问题，保留最新任务、序列和命中信息。
- 查询点击与结果遥测改为批量写入 SQLite，并限制高频遥测保留量；订单提交和恢复证据仍即时持久化且不会被清理。
- 配置、主题和通知设置改为原子替换写入，读取失败会给出可见告警；Windows 通知密钥使用当前用户 DPAPI 加密，渲染进程仅接收脱敏状态。
- 同步 Electron、Python 与安装包版本为 0.4.1，增加订单证据、状态竞态、落库性能、原子写入和凭据保护回归测试。

## 0.4.0 - 2026-09-20

- 修复官方确认按钮可见但提交事件尚未绑定时提前点击的问题：等待官方启用状态后再自动确认；支持延迟弹窗、按钮重绘和未送达点击的处理，未知回执不重复提交。
- 识别官方“正在处理”和排队弹窗，等待订单结果；支持提交后待支付页面的订单号、车次、日期、区间、乘客与席别核对，排队期间不跳转页面。
- 已核对的待支付或成功订单自动清除残留人工核查提示。
- 系统设置中的“检查登录”显示检查进度和结果，区分登录失效、网络异常和浏览器已关闭，并限制检查等待时间。
- 同步 Electron、Python 与安装包版本为 0.4.0，补充对应的浏览器、后端与界面回归测试。

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
