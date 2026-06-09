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
