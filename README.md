# RailWatch 12306

RailWatch 12306 是一个开源的 12306 桌面出行监控操作台。它使用 PySide6 提供产品化界面，并复用 Selenium 监控核心，帮助用户在本机完成车票查询、目标车次监控、候补提醒和本地配置管理。

> 免责声明：本项目仅供学习研究和个人出行辅助使用。请遵守 12306 用户协议、网站规则和所在地法律法规。项目不破解验证码、不伪造官方接口、不保证购票成功。刷新频率建议保持在合理范围内，避免对服务造成压力。

## Product Direction

默认 UI 方向为 **RailWatch Operations Console**：左侧导航、顶部任务状态、中心行程/监控工作区、右侧实时事件面板。整体视觉采用低噪声浅色主题，主色为 RailWatch green，辅助色为 signal blue，强调长期监控时的可读性和可控性。

备选视觉方向保留为产品设计讨论用：

- Professional Operations Console：专业监控操作台，本轮默认实施。
- Lightweight Travel Companion：轻量旅行工具，更适合低频用户。
- Developer Dashboard：面向开源贡献者的诊断仪表盘。

## Screenshots

截图占位，发布前请补充实际界面图：

- `docs/screenshots/dashboard.png`：Dashboard 状态总览
- `docs/screenshots/trip-setup.png`：Trip Setup 行程配置
- `docs/screenshots/monitor.png`：Monitor 查询结果与监控工作区
- `docs/screenshots/settings.png`：Settings 本地数据与安全控制

## Features

- PySide6 桌面操作台：`Dashboard`、`Trip Setup`、`Monitor`、`Settings` 四个主区域。
- 统一状态模型：环境检测、登录状态、查询准备、监控运行、命中结果、候补状态和错误信息集中展示。
- 车票查询分析：自动填入出发站、到达站、日期并解析查询结果。
- 余票监控：支持多个车次和多个席别目标，命中后弹窗和日志提醒。
- 候补识别：将“候补”与真实余票区分，避免把候补状态误判为有票。
- 自动化护栏：自动提交、自动候补、关闭浏览器、清理本地数据等危险操作需要确认。
- 事件日志：按级别筛选，可一键导出。
- 本地隐私：配置、日志和 Chrome profile 默认保存在用户数据目录。

## Requirements

- Python 3.8+
- Chrome 浏览器
- ChromeDriver，版本需与 Chrome 匹配
- Windows/macOS/Linux 桌面环境

## Install

```bash
pip install -r requirements.txt
```

开发模式也可以安装为本地可编辑包：

```bash
pip install -e .
```

ChromeDriver 不随源码仓库提交。如果需要手动放置 ChromeDriver，请下载与 Chrome 匹配的版本，并将 `chromedriver.exe` 放到项目根目录、RailWatch 用户数据目录，或加入系统 `PATH`。

Windows 用户数据目录：

```text
%LOCALAPPDATA%\railwatch-12306
```

## Run

```bash
python t12306_gui_0.py
```

`t12306_gui_0.py` 现在作为兼容入口：默认启动 PySide6 版 RailWatch 12306；如果没有安装 PySide6，会回退到 legacy Tkinter UI。

## Basic Workflow

1. 在 `Settings` 点击 `Check environment`，确认 Python、Selenium、ChromeDriver 可用。
2. 点击 `Open login`，在打开的 12306 页面手动完成登录和验证码。
3. 在 `Trip Setup` 填写出发站、到达站、日期、车次、席别和乘车人配置。
4. 点击 `Analyze query`，让 RailWatch 打开查询页并解析结果。
5. 在 `Monitor` 点击 `Start monitor`，开始受控刷新监控。
6. 命中目标后，根据浏览器页面和 RailWatch 提示完成后续人工确认与支付。

## Packaging

```bat
package.bat
```

打包产物：

```text
dist\RailWatch 12306\RailWatch 12306.exe
```

也可以使用 PyInstaller spec：

```bash
pyinstaller RailWatch_12306.spec
```

当前 spec 文件为 `RailWatch_12306.spec`，产物名为 `RailWatch 12306`。如果项目根目录存在 `chromedriver.exe`，打包脚本会自动将其带入产物；否则用户需要单独提供 ChromeDriver。

## Project Structure

```text
sucess_12306/
├── railwatch_state.py       # UI-facing 状态模型
├── railwatch_ui.py          # PySide6 产品界面
├── t12306_gui_0.py          # 兼容入口与 legacy Tkinter UI
├── gui_12306_0.py           # 12306 查询和监控核心逻辑
├── anti_detect.py           # 浏览器 profile 与行为模拟辅助
├── tests/                   # 单元测试
├── docs/                    # 发布检查等项目文档
├── RailWatch_12306.spec     # PyInstaller 打包配置
├── pyproject.toml           # 开源包元数据
├── requirements.txt         # 依赖列表
├── package.bat              # Windows 打包脚本
├── CONTRIBUTING.md
├── SECURITY.md
├── PRIVACY.md
├── CHANGELOG.md
└── README.md
```

## Privacy

RailWatch 12306 默认将运行时数据写入系统用户数据目录，而不是源码目录。典型内容包括：

- `user_config.json`：行程与监控配置
- `railwatch.log`：事件日志
- `chrome_profile_12306/`：Chrome 登录态、cookie、session 和浏览器缓存
- `device_profile.json`：本机浏览器辅助配置
- `station_codes_cache.json`：站点编码缓存

这些文件不应提交到 Git。`.gitignore` 已覆盖常见敏感文件和本地运行目录。

## Safety Notes

- 自动提交和自动候补默认关闭。
- 自动提交、自动候补、关闭浏览器、清理本地数据都会触发确认。
- 登录验证码、订单确认和支付仍需用户在官方页面完成。
- 如遇页面结构变化、验证码或异常风控，请停止监控并人工处理。

## Tests

```bash
python -m unittest discover -s tests -p "test_*.py"
python -m py_compile railwatch_state.py railwatch_ui.py t12306_gui_0.py gui_12306_0.py anti_detect.py
```

GitHub Actions 已提供 `CI` 工作流用于 pull request 验证，并提供 `Package Windows` 手动工作流用于生成 Windows 桌面包。

当前新增覆盖：

- RailWatch 品牌与四页信息架构
- UI 状态模型默认安全策略
- 环境、登录、查询、监控、命中和错误状态转换
- 命中状态在停止监控后不被覆盖

## Contributing

欢迎提交 issue 和 pull request。建议贡献时优先保持以下边界：

- UI 层只负责状态、表单、事件和展示，核心监控逻辑保持在 `gui_12306_0.py`。
- 新增自动化行为必须默认关闭，并配套明确的用户确认。
- 不提交个人配置、日志、cookie、Chrome profile 或打包产物。
- 修复逻辑问题时优先补充单元测试。

## License

MIT License
