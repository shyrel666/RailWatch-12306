# RailWatch 12306

RailWatch 12306 是一个开源 Electron 桌面应用，用 React/Vite 提供本地 12306 出行监控操作台，并通过内置 Python runtime 复用 Selenium 查询与监控核心。它面向个人出行辅助场景：保存本地行程配置、打开官方 12306 页面、解析查询结果、受控刷新监控目标车次，并在命中时提醒用户人工确认。

> 免责声明：本项目仅供学习研究和个人出行辅助使用。请遵守 12306 用户协议、网站规则和所在地法律法规。RailWatch 不破解验证码、不绕过登录、不调用非公开接口、不保证购票成功，也不会替用户完成支付。

## Current Status

- 当前版本为 v0.3.0，交易自动化仍为实验性功能，需真实账号人工验收。
- 当前主界面为 Electron + React/Vite。
- Python 只保留 runtime 与 Selenium 核心，桌面界面统一由 Electron 提供。
- Windows 打包链路已接入 electron-builder + PyInstaller runtime。

## Features

- 四个主区域：`Dashboard`、`Trip Setup`、`Monitor`、`Settings`。
- 本地配置保存：出发站、到达站、日期、车次、席别、乘客、刷新间隔和定时启动。
- 环境检查：Python、Selenium、Chrome 和 ChromeDriver 状态提示。
- 官方页面登录：打开 12306 登录页，由用户手动完成验证码和登录。
- 查询分析：打开查询页并解析页面结果。
- 监控提醒：目标车次/席别命中后写入事件日志并弹出提醒。
- 定时查询：设置完整北京时间起售时刻，提前准备页面，用系统校时及单调时钟等待；HTTP时间只作辅助检查。旧版时分秒不会自动顺延到次日。
- 实验性交易辅助：先检查全部目标车次的现票，均无票后提交首选候补；明确售罄才自动回退，结果未知则保留订单意图并转人工核对。
- 订单跟踪：SQLite保存提交意图和匹配订单证据，区分预订待支付、候补待支付、生效及兑现；重启后可继续核对，禁止盲目重放。核验及支付由用户完成，真实账号流程尚待验收。
- 安全护栏：自动提交、自动候补、关闭浏览器、清理本地数据等危险操作需要确认。
- 隐私优先：配置、日志、Chrome profile 和 cookie 默认仅保存在本机用户数据目录。

## Requirements

- Windows 10/11, macOS 或 Linux 桌面环境
- Node.js 20+
- Python 3.10+（与已固定的Selenium／requests版本一致）
- Chrome 浏览器
- ChromeDriver，版本需与 Chrome 匹配

## Quick Start

```bash
python -m pip install -r requirements.txt
npm install
npm run dev
```

开发模式会启动 Vite renderer，并打开 Electron 桌面窗口。Electron 主进程会启动 `railwatch_runtime.py`，由 Python runtime 调用 Selenium 核心。

## Basic Workflow

1. 在 `Settings` 点击 `检查环境`，确认 Python、Selenium、Chrome 和 ChromeDriver 可用。
2. 点击 `打开登录`，在官方 12306 页面手动完成登录和验证码。
3. 在 `Trip Setup` 填写出发站、到达站、日期、车次、席别、乘客和监控参数。
4. 点击 `保存` 保存本地配置。
5. 点击 `查询余票`，让 RailWatch 打开查询页并解析结果。
6. 在 `Monitor` 点击 `启动监控`，开始受控刷新。
7. 命中目标后，根据浏览器页面和 RailWatch 提示完成后续人工确认与支付。

## Scripts

```bash
npm run dev              # Electron + Vite 开发模式
npm run test             # Electron main/preload/client 测试 + React renderer 测试
npm run build            # TypeScript 检查 + Electron main build + Vite build
npm run build:runtime    # PyInstaller 构建 Python runtime
npm run package          # 构建 Windows Electron 安装包
```

Python 验证：

```bash
python -m unittest discover -s tests -p "test_*.py"
python -m py_compile railwatch_state.py gui_12306_0.py anti_detect.py chromedriver_manager.py railwatch_preferences.py railwatch_bridge.py railwatch_runtime.py
```

## Packaging

```bash
.\package-windows.cmd 0.2.0
```

该一键脚本会设置 `package.json` / `package-lock.json` 版本号，复用已安装依赖，清理旧的 `release/` 输出，然后执行底层 `npm run package`。如果需要强制重装 Node 和 Python 打包依赖，使用：

```bash
.\package-windows.cmd 0.2.0 --install-deps
```

底层打包链路会执行：

- 构建 Electron main/preload
- 构建 React/Vite renderer
- 使用 `RailWatch_runtime.spec` 打包 Python runtime
- 使用 `electron-builder.yml` 生成 Windows 安装包和 `release/win-unpacked`

发布 GitHub Release 时上传同一次构建生成的 `release/*.exe`、`release/*.blockmap` 和 `release/latest.yml`。

## Architecture

```text
Electron main
  ├─ creates desktop BrowserWindow
  ├─ exposes a restricted preload IPC API
  └─ starts the Python runtime over JSON Lines stdio

React renderer
  ├─ renders Dashboard / Trip Setup / Monitor / Settings
  ├─ owns local UI state through Zustand
  └─ calls runtime commands through preload

Python runtime
  ├─ railwatch_runtime.py: JSON Lines command loop
  ├─ railwatch_bridge.py: frontend-neutral command facade
  ├─ gui_12306_0.py: Selenium query and monitor core
  ├─ railwatch_order_page.py: verified page transactions and reconciliation
  └─ railwatch_orders.py: durable intent, order evidence and stage timestamps
```

## Project Structure

```text
sucess_12306/
├── electron/                # Electron main, preload and Python runtime client
├── src/                     # React renderer, components, store and tests
├── tests/                   # Python runtime/core tests
├── docs/                    # Release QA and publishing checklists
├── assets/                  # App icon and packaged static assets
├── gui_12306_0.py           # 12306 query and monitor core
├── anti_detect.py           # Browser profile and behavior helpers
├── chromedriver_manager.py  # ChromeDriver detection/download helper
├── railwatch_state.py       # Shared state model
├── railwatch_preferences.py # Local UI preferences used by Electron
├── railwatch_bridge.py      # Python command facade for Electron
├── railwatch_runtime.py     # JSON Lines Python runtime process
├── RailWatch_runtime.spec   # PyInstaller runtime build
├── electron-builder.yml     # Electron package config
├── package.json             # Node scripts and frontend dependencies
└── requirements.txt         # Python runtime/core dependencies
```

## Privacy

Runtime data is stored outside the source directory. On Windows the default path is:

```text
%LOCALAPPDATA%\railwatch-12306
```

Typical local files include `user_config.json`, `railwatch.log`, `ui_preferences.json`, `chrome_profile_12306/`, `orders.sqlite3` and `station_codes_cache.json`. The order journal contains passenger names and trip snapshots. Do not commit these files or screenshots containing personal ticket/order/account information.

## Safety Notes

- Automatic submit and automatic alternate are disabled by default.
- Browser environment helpers keep local Chrome profile and page-visible values stable for low-frequency monitoring.
- RailWatch does not bypass login, captcha, payment, website rules or service rate limits. Opt-in automatic submission may click the official order confirmation after verifying the configured trip.
- New automation behavior must be opt-in and guarded by explicit confirmation.
- Stop monitoring if 12306 shows verification, risk prompts or unusual page states.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request. Please keep changes inside the Electron renderer, Electron main/preload, Python runtime, or Selenium core boundary that matches the problem being solved.

## License

MIT License. See [LICENSE](LICENSE).

## 可靠性行为

- 定时目标在启动请求时固定；初始化超过冲刺窗口后继续普通监控，不会因初始化耗时改到次日。
- 任务包含准备、等待、查询、退避、停止中和终态。停止后需等待浏览器操作退出才能重启或关闭浏览器。
- 查询必须通过字段回读和本轮 DOM 更新校验；旧表格、迟到结果、导航或改参后的结果不会用于命中。
- 仅明确的未起售提示可自动关闭；登录、核验、订单确认、频率限制及未知弹窗转人工处理。
- 日期按北京时间校验；范围内无效日期会提示并跳过，全部无效时阻止执行。运行中的任务使用启动时配置。
- 前端正常日志及暂停日志各保留最近 1,000 条，虚拟滚动展示；被丢弃的日志数量会显示在事件面板。

浏览器回归使用独立临时 Chrome profile 和本地 HTML，不访问真实购票页面：

```bash
python -X utf8 tests/browser_smoke.py
python -X utf8 tests/order_browser_smoke.py
python -X utf8 tests/timing_smoke.py --samples 1000
```

需先安装匹配的 ChromeDriver。Windows 打包后可运行 `python -X utf8 tests/packaged_smoke.py`，使用临时用户数据验证 Electron、preload 和内置 runtime；截图保存在 `build/qa/`。

本轮交易状态、恢复规则、定时实测和仍需真实账号验证的项目见 [交易可靠性实现与验收记录](docs/transaction-reliability.md)。真实验证前不宣称可靠自动候补或保证抢到票。
