# 代码审查修复实施与验收记录

实施日期：2026-09-27 至 2026-09-28。依据 `CODE_REVIEW_VALIDATION_PLAN.md`，在原有未提交工作树上实施；保留既有修改，没有提交 Git、发布版本或进行真实购票。

## 已落地行为

| 范围 | 实施结果 | 主要位置 |
| --- | --- | --- |
| C1：确认回执 | 明确区分未派发、已派发、结果未知。未知回执不重复点击、不授权自动导航；上层售罄分支也只读取当前页面。人工提示要求先核对订单，不再引导重复确认。 | `railwatch_order_page.py`、`gui_12306_0.py` |
| H2：无订单证据 | 空列表不再证明未创建订单。journal 在同一写事务中检查提交、确认尝试、恢复记录；提交尝试后即使上层误传 no_order，也保留未决状态。仅明确提交前失败可触发候补回退。 | `railwatch_orders.py`、`railwatch_order_page.py` |
| H1：快照失效 | 元素失效向上传递，最多重取一次当前查询的快照；必须仍属于同一查询及表单，且没有核验弹窗。持续失效显示原因并进入下一轮，不作无票或候补判断。 | `gui_12306_0.py`、`railwatch_row_parser.py`、`railwatch_query.py` |
| H3：启动确认 | 主进程忽略调用方 confirmed，发起一次包含实际路线、日期、车次、席别、乘客及自动化模式的摘要确认。确认期间配置变化拒绝启动；后端再次验证执行日期。 | `electron/main.ts`、`electron/ipcSecurity.ts`、`src/components/MonitorPage.tsx` |
| M4/M5：浏览器可靠性 | 读取乘客采用空闲任务占位，驱动 I/O 不持任务锁；结合明确的会话异常、服务进程和只读探测判断会话存活，未知传输异常保留句柄。 | `railwatch_bridge.py` |
| M9：运行时恢复 | 自动重试最多 5 次，间隔为 1/2/4/8/16 秒；启动后须在 10 秒内完成就绪握手，稳定运行 30 秒后重置失败计数。重试耗尽提供手动入口，退出期间不重启。 | `electron/pythonRuntime.ts`、`electron/main.ts`、`src/App.tsx` |
| M11：协议隔离 | 验证 UTF-8、JSON 对象、id、命令和 payload；坏行返回协议错误，下一条合法命令继续执行。错误提示不回显原始载荷，也不冒充运行时死亡事件。 | `railwatch_runtime.py`、`src/App.tsx` |
| L12：IPC | 事件入口受控拒绝不可信来源，不向事件循环抛错；停止告警入口验证来源，移除无用途 urgent-alert 通道。 | `electron/main.ts`、`electron/alertManager.ts`、`electron/preload.ts` |
| H4/L2：订单与人工动作 | 订单有独立阶段投影；结构化人工动作进入状态，渲染器重载可恢复，Python 重启由未决 journal 重建提示。用户关闭的同一提示不会被后续状态同步反复打开。 | `railwatch_state.py`、`railwatch_bridge.py`、`src/store/railwatchStore.ts` |
| M1：手动查询 | 查询期间改变条件，明确提示本次结果已作废；继续拒绝迟到的旧响应。 | `src/store/railwatchStore.ts` |
| M6：订单观察 | 本地观察预算为 600 秒，读取间隔从 1 秒退避至 5 秒、15 秒；可取消。预算结束提示人工处理，保留未决订单，任务真正结束后释放浏览器占位。 | `railwatch_bridge.py` |
| L7：日志时间 | Python 日志及 Electron 转发的运行时错误均使用完整北京时间 ISO 时间戳，包含日期和 +08:00；导出保留原始时间，默认文件名标注 UTC8。 | `railwatch_bridge.py`、`electron/main.ts` |
| L14：历史记录 | 从数据库全量事件判断关键证据是否存在；另用 events_truncated 表示界面最多返回 500 条，明确展示截断提示。 | `railwatch_orders.py`、`src/components/OrderCenterPage.tsx` |
| M10：发行完整性 | wheel 声明包含 railwatch_sale_times；删除旧模块后同步修正模块清单。已在隔离安装环境验证导入及 stationSaleTimes 命令。 | `pyproject.toml` |
| M7：启动加载错误 | 捕获页面加载 Promise 与主框架加载失败，过滤取消和重复事件，提供原生错误提示及重试。 | `electron/main.ts` |
| M2/M3/L9：开销 | 日志统一格式化一次再计算过滤及计数；查询轮询合并三个脚本为一次浏览器快照，保留核验检查频率；滚动值未变化时不分配新状态。 | `src/lib/formatEventLog.ts`、`src/components/EventPanel.tsx`、`railwatch_query.py`、`src/components/VirtualEventList.tsx` |
| L1/L3/L4/L5/L6/L8：维护 | 删除无消费者 orderStage、无用途线程列表及包装、旧列索引 getter、VerificationDetector；响应资源显式关闭；job 只保留行程字段。 | Python 查询、桥接、配置模块 |
| M8/L11/L13：更新接口 | 按 updater 事件明确 hasUpdate；删除未接入生产的旧下载/校验路径与无意义 force 参数，继续使用现有 electron-updater。 | `electron/updateManager.ts`、`electron/updateChecker.ts`、前端更新接口 |

600 秒为本地资源占用预算，让用户有时间处理支付，同时避免持续占用浏览器；它不是官方支付时限，不会取消、释放或改写官方订单。

## 验证结果

| 验证 | 结果 | 证据 |
| --- | --- | --- |
| Python 全套单元测试 | 319 项通过 | `build/qa/review-python-final.log` |
| Electron 单元测试 | 74 项通过 | `build/qa/review-npm-final.log` 中 Electron 部分 |
| renderer 单元测试 | 190 项通过，35 个文件 | `build/qa/review-renderer-final.log` |
| 查询浏览器测试 | 25 项通过 | `build/qa/review-query-browser-final.log` |
| 订单浏览器测试 | 38 项通过 | `build/qa/review-order-browser-final.log` |
| 类型检查及应用构建 | npm run build 通过 | `build/qa/review-app-build.log` |
| PyInstaller 运行时构建 | 通过 | `build/qa/review-runtime-build.log` |
| 打包运行时恢复 | 未决订单恢复、重复启动/清理阻断、加密凭据及损坏回退通过 | `build/qa/review-runtime-smoke.log` |
| wheel/sdist | 构建及隔离安装通过；wheel 源码与最终工作树核对一致 | `build/qa/python-distribution-final.log`、`build/qa/python-distribution.json` |
| Windows 安装包及桌面烟测 | NSIS 构建通过；打包程序的 preload、运行时、旧配置、草稿、旧订单、可启动状态及停止命令通过 | `build/qa/review-package-build.log`、`build/qa/review-packaged-smoke-result.log`、`build/qa/packaged-monitor.png` |

新增故障场景包括确认事件已发生但节点替换导致回执丢失、订单在 1.2 秒后出现而此前列表为空、class 与空提示不同组合、真实 stale WebElement、有界重取与查询归属变化、已提交后错误 no_order、售罄上层导航旁路、慢乘客读取、坏协议行、有限恢复/观察、历史事件超过 500 条等。

浏览器测试使用独立临时配置与本地夹具，阻断 12306 网络；发行物烟测使用临时用户数据，不提交真实订单。查询性能验收确认每个观察周期一次脚本、持续等待段不超过 10.5 次/秒（含计时容差），额外初始化脚本为 3 次。没有将原报告未经本轮复测的耗时数字写成修复收益。

首次最终 npm test 与 Python 构建、浏览器套件同时运行时，renderer 出现 3 个超时和 1 个刷新断言失败；按 maxWorkers=2 完整重跑后 190 项通过，没有放宽断言或测试超时。原始失败输出予以保留。计数变化还包括删除 2 个仅覆盖退役 VerificationDetector 的测试及 1 个仅覆盖退役下载函数的测试。

桌面烟测截图已检查，页面正常显示。退出阶段日志记录了一次仍在等待的 IPC 请求被 runtime stop 拒绝；进程正常退出，功能断言均通过。这不影响上述烟测结果，但本次没有将关闭期间的日志降噪列为新增修复。

## 交付及保留限制

- Python 发行物：`build/review-dist/railwatch_12306-0.4.2-py3-none-any.whl`、`build/review-dist/railwatch_12306-0.4.2.tar.gz`。
- Windows 安装包：`release/review-20260928/RailWatch-12306-0.4.2-x64.exe`，与原 release/win-unpacked 分开。烟测启动同次构建的 win-unpacked 程序；未在本机安装或执行安装/卸载升级测试。
- 环境及依赖信息：`build/qa/review-environment.json`，包括 package-lock SHA-256。发行物摘要另存 `build/qa/review-artifacts.json`。
- 工作前基线位置记录于 `tmp/review-baseline-location.txt`；本轮对比记录为 `build/qa/review-only.patch` 和 `build/qa/review-changed-files.json`。故障测试文件最初 3 个用例在基线保存前已新建，因此该补丁不是全部新增文件的独立安装包；应连同当前工作树审阅。
- M12 维持撤回；L10 保留生产 sequence/loop 同源约束，不放宽重复或错误条件快照的计数规则；站名后缀适配继续等待官方页面证据。
- 主题确认用于防误操作和流程一致性。渲染器仍承载确认 UI，不能将它宣称为抵御任意渲染层代码执行的安全边界。
- 运行时就绪不证明旧浏览器及在途订单已清理，因此保留 runtimeContinuityUnknown 对更新安装的保守阻断。
- 提交后空页即使长时间存在也不自动判为无订单；这会减少自动售罄转候补，需人工核对。真实账号下的官方空状态、站名、候补截止时间和订单呈现仍须发布前验收。本轮没有线上购票或发布。
