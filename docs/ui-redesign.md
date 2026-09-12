# 桌面界面与主题重设计

界面以当前行程和下一步操作为中心，统一使用雾白／石墨灰背景及青绿强调色。侧栏可以折叠，日志从常驻第三栏改为按需打开的抽屉，系统信息集中在设置页。

## 实现约定

- `src/lib/theme.ts` 定义两套语义颜色及 Ant Design 配置；`useThemePreference` 负责跟随系统、加载与保存偏好。CSS 变量应用于文档根节点，弹窗和下拉菜单使用同一套主题。
- 偏好文件支持 `system`、`light`、`dark`；已有明暗偏好继续有效，缺失或损坏的配置回退 `system`。本地浏览器缓存只用于首次绘制，Python 偏好文件为持久化来源；保存失败恢复原主题。
- 首页按未解决订单、人工操作、运行状态及准备阶段选择下一步。首页和监控页共用订单未解决判定；运行中继续使用任务启动时的配置快照。
- 行程设置保留全部原有字段，分为路线与乘客、查询策略、定时启动、自动化。首页可定位并打开相应分组；导航只滚动页内内容。
- 日志默认关闭，关闭时仍接收事件；筛选与暂停状态保留在当前会话。抽屉支持 Esc 和关闭后返回入口焦点。高优先级通知仍独立展示。
- 窗口最小尺寸仍为 1180×720；小于 1280px 默认收起侧栏。保存与查询操作固定在表单底部，监控操作保持在内容区顶部。

## 自动验证

```powershell
npm test
npm run build
python -m unittest tests.test_railwatch_preferences tests.test_railwatch_runtime tests.test_railwatch_bridge
```

已通过：前端 92 项测试、Electron 31 项测试、Python 44 项测试，以及类型检查与完整构建。测试包含主题保存失败回退、系统主题切换、正文对比度、日志键盘操作、订单优先级、配置快照及原有业务命令回归。

## 可重复的视觉检查

`scripts/review-ui.cjs` 使用 Playwright 和本机 Google Chrome，以模拟的 `window.railwatch` 桥接数据运行真实前端；不连接账号或真实订单。先启动 `npm run dev:renderer`，在另一个终端运行 `npm run review:ui`。

运行环境需要提供 Playwright 包，可以使用 `RAILWATCH_PLAYWRIGHT` 指向已有的 Playwright 模块目录；未设置时按 Node 标准规则加载 `playwright`。`RAILWATCH_PREVIEW_URL` 可指定 Vite 地址，默认 `http://127.0.0.1:5173`。Playwright 不属于生产依赖。

脚本检查全部五个页面在两套主题和三种尺寸下的 30 个组合：1180×720、1440×900、1920×1080。额外在 1180×688 验证长车次列表、长查询结果与异常信息，检查内容宽度及固定操作栏，并验证日志筛选、焦点恢复、订单定位和取消自动化确认。

输出位于 `build/ui-review/`：

- `dashboard-light.png`、`dashboard-dark.png`：首页明暗主题。
- `<宽度>-<light|dark>-<dashboard|trip|monitor|settings|about>.png`：页面尺寸矩阵。
- `monitor-running-dark.png`、`monitor-attention-dark.png`：运行与待处理订单。
- `log-drawer-dark.png`、`automation-confirmation-dark.png`：抽屉及确认弹窗。
- `stress-*.png`：最小可用高度下的长内容场景。
- `report.json`：尺寸测量、浏览器错误及模拟命令记录。

这些截图验证的是实际渲染器。真实账号、订单提交和打包安装程序未纳入此次视觉验收。
