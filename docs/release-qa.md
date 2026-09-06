# RailWatch 12306 Release QA

本清单用于 Electron-only 打包版发布前验证。自动化测试不能替代真实 12306 页面、ChromeDriver 和人工登录流程。

## 自动化验证

- `npm run test`
- `python -m unittest discover -s tests -p "test_*.py"`
- `npm run build`
- `.\package-windows.cmd 0.2.0`
- 仅在依赖缺失或需要重装时使用 `.\package-windows.cmd 0.2.0 --install-deps`
- 启动 `release/win-unpacked/RailWatch 12306.exe`，确认窗口、React renderer、preload API 和 Python runtime 都能启动。
- 发布时只上传同一次构建生成的 `release/*.exe`、`release/*.blockmap` 和 `release/latest.yml`。

## 手工功能验证

- 在 `Settings` 执行 `检查环境`，确认 Python、Selenium、Chrome、ChromeDriver 状态正确。
- 执行 `打开登录`，在官方 12306 页面手动完成登录和验证码。
- 在 `Trip Setup` 填写出发站、到达站、日期、车次、席别、乘客和刷新间隔，保存后重启应用确认配置仍在。
- 执行 `查询余票`，确认查询页打开、查询结果表格有解析输出，事件面板记录对应日志。
- 在 `Monitor` 执行 `启动监控` 和 `停止监控`，确认按钮状态、状态摘要、事件日志都按运行状态变化。
- 尝试启用 `有票时自动提交` 和 `仅候补时自动排队`，确认都会先弹出确认。
- 使用事件面板筛选、暂停、清空和导出日志，确认导出文件可读。
- 切换暗色模式并重启应用，确认偏好保存。
- 退出应用后检查没有残留的 `RailWatch 12306.exe` 或 Python runtime 进程。

## 安全回归

- 自动提交和自动候补默认必须关闭。
- 登录、验证码、订单确认和支付仍必须在官方页面人工完成。
- 清除本地数据、关闭浏览器等危险操作必须通过 UI 明确触发。
- 不提交用户配置、日志、cookie、Chrome profile、安装包或打包中间产物。

## 任务可靠性回归

- 运行 `python -X utf8 tests/browser_smoke.py`：真实 Chrome 仅加载本地页面夹具，验证结果更新、空结果、迟到响应、改参及弹窗白名单。
- 打包后运行 `python -X utf8 tests/packaged_smoke.py`：隔离 APPDATA/LOCALAPPDATA，检查四个页面、preload、旧配置加载与保存、runtime 新字段和无历史查询时的启动条件。
- 验证初始化跨过目标秒仍在当日执行；超过冲刺窗口转普通监控。
- 验证停止中不能重启、关闭浏览器或清理数据；停止前发出的浏览器请求可以完成，但不再发出后续操作。
- 验证登录明确失效及连续三次未知结果会停止；重新登录后需手动启动。
- 核验、订单及未知弹窗不得被查询失败处理器自动确认。
- 日期范围部分有效时仅查询有效日期，跨北京时间午夜后重新过滤；全部无效时拒绝执行。
- 编辑表单不改变正在运行的任务；行程显示完整站名。
- 向前端输入大量日志，确认缓冲区不超过上限、滚动不产生重复行，暂停恢复后提示丢弃条数。

本地夹具和打包冒烟不代表真实 12306 登录、查询和候补流程已验收；发布前仍由维护者按上面的手工功能清单验收，不在自动测试中提交真实订单。
