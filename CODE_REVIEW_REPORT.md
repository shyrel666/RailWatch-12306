# RailWatch 12306 代码审查与问题修复报告

| 项目 | 内容 |
| --- | --- |
| 审查日期 | 2026-09-27 |
| 代码版本 | 工作区 `0.4.2`（本地候选构建 2026-09-23 之后的未提交工作树） |
| 审查范围 | `railwatch_*.py`、`gui_12306_0.py`、`anti_detect.py`、`chromedriver_manager.py`、`electron/*.ts`、`src/**`、打包与 CI 配置 |
| 审查方法 | 逐行静态审查 + 真机动态验证（真 Chrome 153 + 匹配 ChromeDriver，`tests/fixtures/*.html`，Python/Node 双测试套件） |
| 基线状态 | `python -m unittest discover -s tests -p "test_*.py"` → **312 passed**；`npm test` → electron 套件 + **188 renderer tests passed** |
| 结论摘要 | 确认 **20 项**问题（1 严重 / 4 高危 / 11 中危 / 4 低危）另加 **10 项**代码卫生项；其中 **15 项经真机或测试套件动态复现**，其余为静态确证；**1 项在动态验证后被撤回**（M12），**2 项描述按实测数据修正**（M2、L8），**1 项为动态验证中新发现**（站名粘连脆弱性，见附录 C） |

> 本报告所有行号均对应当前工作区文件；链接形如 `file.py#L496-L512` 可在 GitHub/编辑器中直接跳转。
> 动态验证脚本未写入仓库，位于 `%TEMP%\rw-verify\`，复现命令见附录 B。

---

## 0. 摘要

### 0.1 问题分布

| 严重度 | 数量 | 编号 | 已动态证实 |
| --- | --- | --- | --- |
| 严重 Critical | 1 | C1 | ✅（真实页面 fixture 复现） |
| 高危 High | 4 | H1 H2 H3 H4 | ✅（H1/H2/H4 真机；H3 单测） |
| 中危 Medium | 11 | M1–M11 | ✅ 8 项（M1 M2 M3 M4 M6 M8 M10 M11）；M5/M7/M9 为静态确证 |
| 低危 Low（需修） | 4 | L2 L3 L4 L6 | ✅（grep/源码级确证） |
| 代码卫生 Low | 10 | L1 L5 L7–L14 | 部分（L8/L10 已实测） |
| 已撤回 | 1 | M12 | — |

### 0.2 必须优先修的三项

1. **C1 —— 确认按钮"假成功"**：点击未送达 12306 时仍返回成功，导致 5 秒重试被短路，并把用户带离一个尚未提交的订单表单。已用真实页面 fixture 复现：`fixture.confirmClicks 0 → 0`（12306 从未收到确认）而函数返回 `True`。
2. **H1 —— 一个 stale 元素吞掉整轮命中扫描**：结果表自重渲染后有票行被判为"未命中"并睡满一个间隔。真机复现：同一行、同一 DOM，仅句柄过期即从 `hit=('G101','二等座','有')` 变为 `hit=None`。
3. **H2 —— "官方待支付列表为空" fail-open**：页面上明明有订单，仅因行节点 class 改名（或渲染竞态），即被判定为"明确没有订单"，并真的释放防重复提交闸门（`unresolved=0`）。真机复现并写入真实 SQLite 验证。

### 0.3 一句话结论

设计与分层是合理的（意图先落盘再点击、`BEGIN IMMEDIATE` + 唯一索引守卫、失败即转人工），但**三处"证据不足却当作证据"的判断**（确认点击回执、订单列表为空、命中扫描异常）会把"不确定"静默降级为"确定的结论"，恰好都发生在抢票与防重复提交的关键路径上；其余多为性能与工程卫生问题。

---

## 1. 审查与验证方法

### 1.1 分层与职责（审查依据）

```
React 渲染层 (src)  ⟷ 受限 IPC (electron/preload.ts, ipcSecurity.ts)
                    ⟷ Electron 主进程 (electron/main.ts)
                    ⟷ JSON Lines ⟷ Python 运行时 (railwatch_runtime.py → railwatch_bridge.py)
                    ⟷ Selenium ⟷ 单个受控 Chrome ⟷ 12306 官方页面
                    ⟷ SQLite (railwatch_orders.py)
```

### 1.2 证据等级定义

| 等级 | 含义 |
| --- | --- |
| **A 动态证实** | 在真机（真 Chrome / 真测试套件 / 真子进程）上复现，且带可观测输出 |
| **B 静态确证** | 逐行读源码即可判定，无需运行（如条件恒真、异常未捕获、参数被丢弃） |
| **C 机制证实、待线上确认** | 代码机制已证实，但触发需要线上 12306 页面出现特定形态；本报告显式标注 |
| **D 已撤回** | 动态验证推翻，不再视为问题 |

### 1.3 动态验证环境

| 项 | 值 |
| --- | --- |
| Python | 3.10.8（`D:\python-3.10.8`） |
| selenium / requests | 4.44.0 / 2.33.1（与 `requirements.txt` 一致，依赖固定值有效） |
| Chrome / ChromeDriver | 153.0.8010.53 / 153.0.8010.52（数据目录），仓库根另有 148 版驱动 |
| Node / npm | v22.22.1 / 10.9.4 |
| 真机页面 | `tests/fixtures/orders.html`、`tests/fixtures/query.html`（阻断 `*12306.cn*` 网络） |

### 1.4 局限

- 无法在本地访问线上 12306，标记为 **C 级**的结论需要一次真实账号验收。
- 审查对象是**含大量未提交改动的工作树**（`git status` 显示 60+ 修改、40+ 新增文件，含 `railwatch_sale_times.py` 等新模块），结论仅对该工作树成立。

---

## 2. 问题清单

### C1 · 确认按钮点击回执在未送达时仍返回成功（严重 / A 级）

- **状态**：待修复
- **位置**：[`railwatch_order_page.py#L496-L512`](railwatch_order_page.py#L496-L512)、[`#L614`](railwatch_order_page.py#L614)、[`#L530-L531`](railwatch_order_page.py#L530-L531)、[`#L545`](railwatch_order_page.py#L545)

```python
            if observed:
                try:
                    delivered = self.driver.execute_script(CONFIRM_RECEIPT_JS, token, "read")
                    if delivered is False:
                        ...
                        delivered = self.driver.execute_script(CONFIRM_RECEIPT_JS, token, "dispatch")
                    if delivered is True:
                        self.mark("regular_confirm_dispatched")
                        self.log("确认按钮点击事件已触发，正在等待官方订单结果。")
                except Exception:
                    self.log("确认按钮事件回读失败，将核对订单结果，不重复点击。")
            return True
        return click() or self.poll(click, timeout=5, ignore_stop=True)
```

**现象**：`CONFIRM_RECEIPT_JS` 在两种情况下返回 JS `null`（Python `None`）——回执丢失/token 不匹配（[`#L178-L179`](railwatch_order_page.py#L178-L179)），或 `dispatch` 前置守卫拒绝（[`#L181-L184`](railwatch_order_page.py#L181-L184)）。`delivered is False` 分支**只在第一种情况返回 `False` 时才进入**；返回 `None` 时整个 `if` 被跳过，直接落到 `return True`。因此：

- 页面重渲染导致回执丢失时，为它写的 `dispatch` 兜底**根本不会执行**；
- 函数无条件返回真值 ⇒ `click() or self.poll(click, timeout=5)` 的 5 秒重试被短路（与函数注释"Retry only clicks rejected before dispatch"相反）；
- 调用方 [`#L614`](railwatch_order_page.py#L614) `confirmed_clicked = confirmation is True` ⇒ [`_post_submit`](railwatch_order_page.py#L514-L534) 在弹窗消失后会执行 `reconcile(navigate=True)` ⇒ [`#L545`](railwatch_order_page.py#L545) `driver.get(".../train_order.html")`，**导航离开尚未提交的确认页**。

**动态证据**（真 Chrome + `tests/fixtures/orders.html`）：

```
F1  returned=True  fixture.confirmClicks 0 -> 0 (12306 never processed a confirm)  marks=['regular_confirm_attempt']
F2  marks=['regular_confirm_attempt'] -> 无 'regular_confirm_dispatched' 标记、无日志，但返回值真值化了
F3  confirmed_clicked=True -> _post_submit navigated to ['https://kyfw.12306.cn/otn/view/train_order.html']
对照 C1/real-a：弹窗仍可见时 _post_submit 返回 'verification' 且不导航（优雅降级分支）
对照 C1/real-c：confirmed_clicked=False 时不额外导航
```

**影响**：一次未送达的确认被记为"已确认提交"，用户被带离可提交的表单，且没有任何错误提示与重试；本地记录已写入 `regular_confirm_attempt` 标记，后续恢复流程会把结论导向"结果未知 → 人工核对"。

**修复建议**（三态化 + 未确认送达不得导航）：

```python
            if observed:
                try:
                    delivered = self.driver.execute_script(CONFIRM_RECEIPT_JS, token, "read")
                    if delivered is False:
                        result = self.result(intent, submitted=True)
                        if result.status != "unknown":
                            return result
                        self.log("浏览器点击未触发确认按钮，正在直接触发该按钮的点击事件。")
                        delivered = self.driver.execute_script(CONFIRM_RECEIPT_JS, token, "dispatch")
                    if delivered is True:
                        self.mark("regular_confirm_dispatched")
                        self.log("确认按钮点击事件已触发，正在等待官方订单结果。")
                        return True
                    # 回执丢失或兜底守卫拒绝：既不是"已送达"，也不是"确定未送达"
                    self.log("未能确认确认按钮已收到点击（回执丢失或按钮状态已变），本轮不判定为已提交。")
                    return None                      # 交回外层 5 秒重试
                except Exception:
                    self.log("确认按钮事件回读失败，将核对订单结果，不重复点击。")
                    return True                      # WebDriver 侧异常：保持"不重复点击"的保守语义
            return True
```

并在 [`_post_submit`](railwatch_order_page.py#L530) 增加门槛：仅当 `confirmed_clicked is True`（而非真值）时才允许 `navigate=True`。

**回归测试**：把 F1/F2/F3 固化为 `tests/order_browser_smoke.py` 用例——注入"点击不送达 + 节点被重渲染"的确认元素，断言返回 `None`、无 `regular_confirm_dispatched` 标记、`fixture.confirmClicks` 不增长、且不触发导航。

---

### H1 · 一个 stale 元素吞掉整轮命中扫描，误报"未命中"（高危 / A 级）

- **状态**：待修复
- **位置**：[`gui_12306_0.py#L1105-L1142`](gui_12306_0.py#L1105-L1142)、[`gui_12306_0.py#L1091-L1093`](gui_12306_0.py#L1091-L1093)、[`railwatch_row_parser.py#L178-L189`](railwatch_row_parser.py#L178-L189)

```python
    def _find_hit_row(self, seat_col_indices):
        try:
            ...
            for snapshot in rows:            # 整段循环共用一个 try
                ...
        except (NoSuchElementException, StaleElementReferenceException):
            return None                      # 任一行过期 ⇒ 放弃全部 ⇒ "未命中"
```

```python
        if button and button.is_displayed() and button.is_enabled() and button.get_attribute("aria-disabled") != "true":
            return button
      except NoSuchElementException:          # 未捕获 StaleElementReferenceException
        continue
```

**现象**：元素句柄来自 [`#L1043`](gui_12306_0.py#L1043) 的 `snapshot_rows`，而 12306 结果表会自行刷新（fixture 每次点查询即重写 `#queryLeftTable`）。`is_displayed()/is_enabled()/get_attribute()` 在行被重渲染时抛 `StaleElementReferenceException`，`find_button` 未捕获 ⇒ 冒泡到 `_find_hit_row` 的总 `except` ⇒ **第 k 行之后不再检查**，返回 `None` ⇒ [`#L1091-L1093`](gui_12306_0.py#L1091-L1093) 打印 `❌ 未命中目标票，继续监控...` 并 `self._sleep(interval)`。`#L1049` 的 revision 守卫在扫描**之前**，覆盖不到该窗口。

**动态证据**（真 Chrome + 真 `WebElement`）：

```
H1/real-a  fresh snapshot            -> hit=('G101', '二等座', '有')
H1/real-b  结果表重渲染后            -> hit=None（DOM 仍显示 二等座=有）
H1/real-c  对同一 DOM 重新 snapshot   -> hit=('G101', '二等座', '有')
H1c        find_button 让 StaleElementReferenceException 逃逸（仅捕获 NoSuchElementException）
```

**影响**：抢票窗口内一轮有效查询被丢弃并睡满一个间隔（默认 3–6 秒，突发模式同样如此），日志与后续判断都显示"无票"。

**修复建议**：

```python
# railwatch_row_parser.py
      except (NoSuchElementException, StaleElementReferenceException):
        continue
```

```python
# gui_12306_0.py
        for _, train, snapshot in ranked:
            try:
                ...单行逻辑（席别判定 / 预订按钮 / 席别回读）...
            except StaleElementReferenceException:
                raise            # 作废本轮，交由 _query_loop 立即重查而不是报"未命中"
```

**回归测试**：用 `tests/fixtures/query.html` 写用例——`snapshot_rows()` 后执行 `tbody.innerHTML = tbody.innerHTML`，断言 `_find_hit_row` 不返回 `None` 而是抛出让外层作废本轮的信号；同时断言 `find_button` 对过期元素返回 `None` 而不抛异常（两条路径都要覆盖）。

---

### H2 · "官方待支付列表为空"是唯一能自动解除防重复闸门的证据，且建立在选择器推断上（高危 / A 级）

- **状态**：待修复
- **位置**：[`railwatch_order_page.py#L99`](railwatch_order_page.py#L99)、[`#L316-L317`](railwatch_order_page.py#L316-L317)、[`railwatch_orders.py#L175-L181`](railwatch_orders.py#L175-L181)、[`gui_12306_0.py#L725-L730`](gui_12306_0.py#L725-L730)、[`gui_12306_0.py#L739-L743`](gui_12306_0.py#L739-L743)

```js
 pendingEmpty:all('#J-order-payment,#not_complete').some(e=>/您没有待支付|没有未完成|暂无待支付/.test(txt(e))) && orders.length===0 && !all('.loading,.loading-box,#J-loading').length,
```

```python
        if snap.get("pendingEmpty") and not known_id and (not submitted or allow_empty):
            return OrderResult("not_submitted", "官方待支付订单列表明确为空", no_order=True)
```

**现象**：`orders` 完全由 `.order-item`（[`#L55`](railwatch_order_page.py#L55)）+ `getClientRects()` 可见性推断。该分支是**唯一**能把未决订单改判为 `not_submitted/no_order=True` 的自动通路，`record()` 在接受后写入 `unresolved=0`，唯一索引守卫随之释放 → `can_fallback` → `auto_alternate` 立即走候补并允许下一次 `begin()`。代码没有任何"列表容器存在且已被解析"的正向证据。

**动态证据**（真 Chrome 执行真实 `SNAPSHOT_JS`，再交给真实 `OrderPage.result()`）：

```
H2/control  .order-item（仓库自带格式）   orders=1 pendingEmpty=False -> 'pending_payment' order_id='E123456'
H2a         同一页面，仅行 class 改名     orders=0 pendingEmpty=True  -> 'not_submitted' no_order=True
H2b         同一页面，相隔 1.2s          early: not_submitted | late: pending_payment
H2c         该判定写入真实 SQLite         pending()=None -> 唯一索引闸门被释放
```

**影响**：页面上真实存在的订单被判为"不存在"，防重复提交闸门被解除，程序可以再次提交同一车次/日期/乘客；用户侧则被误导为"尚未下单"。此路径是 fail-open，处在最不能 fail-open 的位置。

**修复建议**：把"列表为空"从"没有 `.order-item` 节点"的**消极推断**改为**积极证明**。两个经过验证的失败模式（class 改名 / 渲染竞态）需要两条规则同时生效：

1. **容器文本必须只有空列表文案**——class 改名场景中，容器里还带着真实订单的文本（订单号、车次、席别、乘车人），因此该规则能挡住它；
2. **同一判定需在 ≥300ms 间隔内连续两次成立**——渲染竞态场景中，第一次读数时行还没渲染出来，第二次读数就会带上行文本，因此该规则能挡住它。

```js
// SNAPSHOT_JS：给出可供"积极证明"的原始字段
 orderListPresent: !!document.querySelector('#J-order-payment,#not_complete'),
 orderListLoading: !!all('.loading,.loading-box,#J-loading').length,
 orderListText: txt(document.querySelector('#J-order-payment') || document.querySelector('#not_complete')),
```

```python
    EMPTY_LIST_TEXT = re.compile(r"^(?:您没有待支付|没有未完成|暂无待支付)(?:的?订单)?[。.]?$")

    def _empty_list_proven(self, snap):
        """Only a container whose entire text is the empty-list notice proves 'no order'."""
        if not snap.get("orderListPresent") or snap.get("orderListLoading") or snap.get("orders"):
            return False
        return bool(EMPTY_LIST_TEXT.match(str(snap.get("orderListText", "")).strip()))

    # result() 中：先记录候选，短间隔二次确认后才接受
    def _confirm_empty_once(self, intent, delay=0.35):
        if not self._empty_list_proven(self.snapshot()):
            return OrderResult("verification", "官方订单列表尚未渲染完成，请人工核对")
        self.wait(delay)
        if not self._empty_list_proven(self.snapshot()):
            return OrderResult("verification", "官方订单列表状态不稳定，请人工核对")
        return OrderResult("not_submitted", "官方待支付订单列表确认为空", no_order=True)
```

若不愿改动判空逻辑，最低成本的兜底是：**只要不是"二次确认过的空列表"，就一律降级为 `verification`**——宁可让用户多核对一次，也不要自动释放防重复提交闸门。

**回归测试**：把 `probe_c2.py` 的四个场景（对照 / class 改名 / 1.2 秒竞态 / DB 闸门）写成 fixture 驱动的浏览器用例；断言 class 改名与竞态场景都**不**产生 `not_submitted`。

---

### H3 · 主进程的自动化确认门可由渲染层自行置位（高危 / A 级）

- **状态**：待修复
- **位置**：[`electron/ipcSecurity.ts#L102`](electron/ipcSecurity.ts#L102)、[`electron/main.ts#L416-L423`](electron/main.ts#L416-L423)

```ts
  if (command === "startMonitor" && payload.confirmed !== true) {      // 读调用方 payload
```

```ts
  const confirmation = getCommandConfirmation(command, normalizedPayload);
  const requestPayload = { ...normalizedPayload };                     // 原样透传 confirmed
  if (confirmation) { ... requestPayload.confirmed = true; }
```

**动态证据**：

```
startMonitor payload {confirmed:true}  -> null（无弹窗）
startMonitor payload 无 confirmed      -> 确认自动化（有弹窗）
clearLocalData / closeBrowser / dismissOrder with confirmed=true -> 仍弹窗
转发给 Python 的载荷: {"config":{"auto_submit":true},"confirmed":true}
```

**影响**：任意渲染层脚本 `railwatch.command("startMonitor", { confirmed: true, config: { auto_submit: true } })` 可跳过"确认自动化"弹窗直达 Python（Python 侧 [`railwatch_bridge.py#L822-L823`](railwatch_bridge.py#L822-L823) 也只检查 `confirmed`）。这是**纵深防御缺口**（需先有渲染层代码执行才能利用），但使该门只能挡误操作、不能挡脚本。其余破坏性命令在本层始终弹窗，缺口只在这一个门。

**修复建议**：

```ts
  const { confirmed: _ignored, ...safePayload } = normalizedPayload;
  const confirmation = getCommandConfirmation(command, safePayload);
  const requestPayload = { ...safePayload };
  if (confirmation) { ... requestPayload.confirmed = true; }
```

**回归测试**：在 `electron/__tests__/ipcSecurity.test.ts` 增加用例——`getCommandConfirmation("startMonitor", { config: { auto_submit: true }, confirmed: true })` 必须仍返回提示。

---

### H4 · 订单阶段收尾后 UI 顶部仍显示绿色"监控中"（高危 / A 级）

- **状态**：待修复
- **位置**：[`railwatch_bridge.py#L403-L404`](railwatch_bridge.py#L403-L404)、[`railwatch_bridge.py#L995-L996`](railwatch_bridge.py#L995-L996)、[`src/lib/formatSystemStatus.ts#L46-L48`](src/lib/formatSystemStatus.ts#L46-L48)、[`src/components/Shell.tsx#L264-L274`](src/components/Shell.tsx#L264-L274)

```python
            phase = {"error": AppPhase.ERROR, "stopped": AppPhase.QUERY_READY, "human_action": AppPhase.QUERY_READY,
                     "hit": ...}.get(status, AppPhase.MONITORING)      # 订单阶段落到默认值
```

**动态证据**：

```
task.done.set() 后 _transition(task, 'pending_payment')
-> terminal='pending_payment' phase='monitoring' monitoring=False
```

前端 `formatRuntimePhaseLabel(phase==='monitoring')` → 返回 `"监控中"`，`getRuntimePhaseTone` 给出 active 色调。于是状态栏绿色"监控中"，而仪表盘/监控页按 `status.monitoring` 显示"监控未运行"、停止按钮禁用。

**修复建议**：给订单阶段显式映射非监控 phase，或在 `_transition` 内当 `task.active` 为假时强制 `QUERY_READY`/`HIT`；前端在 `monitoring === false` 时不返回"监控中"。

**回归测试**：`tests/test_railwatch_bridge.py` 增加"订单阶段收尾后 `phase != 'monitoring'` 或 `monitoring == phase 一致`"的断言。

---

### M1 · 查询进行中修改行程配置 → 查询结果被静默丢弃（中危 / A 级）

- **状态**：待修复
- **位置**：[`src/store/railwatchStore.ts#L326-L329`](src/store/railwatchStore.ts#L326-L329)、[`#L265`](src/store/railwatchStore.ts#L265)、[`src/lib/queryResults.ts#L11-L14`](src/lib/queryResults.ts#L11-L14)

**动态证据**：

```
改配置后: manualQueryId=null pending=false views=0 error=null
req-1 回包后: results=0 views=0 error=null          ← 结果被丢弃且无错误
对照（不改配置）: results=1 views=1
```

**影响**：用户等待数十秒后结果面板为空、无任何提示；查询期间表单未禁用（仅按钮 `loading`），"点查询 → 顺手改出发日期/交换出发站"即可触发。

**修复建议**：

```ts
        ...(!get().status.monitoring && changed ? { queryViews: {}, results: [], queryConfig: null, activeQuery: null,
          manualQueryId: null, manualQueryPending: false,
          manualQueryError: get().manualQueryPending ? "行程配置已修改，本次查询已取消" : null } : {})
```

**回归测试**：`src/store/queryResults.test.ts` 增加"配置变更后到达的响应必须留下可见错误"的断言。

---

### M2 · 事件面板每条日志做 5 次全量遍历（中危 / A 级，按实测下调措辞）

- **状态**：待修复（收益确定、改动小）
- **位置**：[`src/components/EventPanel.tsx#L38-L48`](src/components/EventPanel.tsx#L38-L48)、[`src/lib/formatEventLog.ts#L131-L133`](src/lib/formatEventLog.ts#L131-L133)、[`railwatchStore.ts#L259-L260`](src/store/railwatchStore.ts#L259-L260)

**动态实测**（1000 条上限窗口，25 次取中位）：

```
单趟 presentEventLogs           = 0.33 ms
EventPanel 工作量（visible+4counts）= 1.74 ms   → 5.26×（与"5 次全量遍历"一致）
冷启 5 趟                        = 6.5 ms
→ 20 条/秒突发时约 35 ms/s 主线程占用（约 3.5%）
```

`logs` 每次追加都是新数组，两个 `useMemo` 必然失效；`countEventsByFilter` 对 4 个标签各跑一次完整 `presentEventLogs`（含 `stripEmoji`、多条正则、`splitMessage`、`reverse`）。

**修复建议**：四个计数一次遍历算完（或在 `applyLog` 维护增量计数）；`useMemo` 依赖改为 `logs.length` + 末条 id。

**回归测试**：`src/lib/formatEventLog.test.ts` 增加"计数与过滤结果一致"的等价性用例，为后续重构兜底。

---

### M3 · 查询热路径每 100ms 打 3 次驱动往返（中危 / A 级）

- **状态**：待修复
- **位置**：[`railwatch_query.py#L269-L289`](railwatch_query.py#L269-L289)

**动态实测**：计数包装真驱动后，**2.00 秒内 54 次 `execute_script` = 27.0 次/秒**；按默认 `query_timeout = 40`（[`railwatch_config_contract.py#L172`](railwatch_config_contract.py#L172)）≈ **1080 次往返/轮查询**，其中 `QUERY_STATUS_JS` 还要读取并正则扫描整张结果表。

**修复建议**：轮询间隔提到 200–250ms；`inspect_dialog` 只在状态迁移时执行（或并入 `QUERY_STATUS_JS` 一次返回）；`gui_12306_0.py` 内 `current()` 取值一次复用（[`#L1027`](gui_12306_0.py#L1027)、[`#L1049`](gui_12306_0.py#L1049)、[`#L1062`](gui_12306_0.py#L1062) 各自触发 2–3 次脚本调用）。

---

### M4 · `read_passengers` 在持有 `_task_lock` 时执行 Selenium I/O（中危 / A 级）

- **状态**：待修复
- **位置**：[`railwatch_bridge.py#L554-L560`](railwatch_bridge.py#L554-L560)（对比 [`#L233-L249`](railwatch_bridge.py#L233-L249) 的正确模式）

**动态实测**（2.0s 的 `execute_script` 期间，隔离测量）：

```
task_activity() 阻塞 1.75s
stop_monitor()  阻塞 >0.5s
```

**影响**：读取乘客（页面较慢时数秒）期间，心跳（每 0.2s 一次 `_transition`）、`task_activity`、`stop_monitor`、`start_monitor` 全部阻塞：界面"停止监控/结束核对"会卡住，退出前的 `taskActivity` 也会等。`idle_browser_command` 明确采用"锁内占位、锁外干活"，此处偏离。

**修复建议**：改成两段式——`_task_lock` 内只做准入判断与 `_browser_busy` 置位，`execute_script` 在锁外、仅持 `_driver_lock`。

---

### M5 · 瞬时网络错误被判定为"浏览器会话失效"，会杀掉健康 Chrome（中危 / B 级）

- **状态**：待修复
- **位置**：[`railwatch_bridge.py#L130-L141`](railwatch_bridge.py#L130-L141)、[`#L707-L713`](railwatch_bridge.py#L707-L713)、[`#L756-L758`](railwatch_bridge.py#L756-L758)

`SESSION_LOST_MESSAGE_HINTS` 含 `connection refused` / `max retries exceeded` / `unable to connect to`，而 `open_login` 对 `driver.get(LOGIN_URL)` 的异常调用 `is_session_lost` → 判定"窗口被用户关掉" → `_release_driver()` **退出仍健康的浏览器**并重启，丢失页面状态；`check_login` 同样丢句柄。

**修复建议**：会话失效只认 WebDriver 会话类异常；`connection refused`/`max retries exceeded` 归为可重试传输错误，重试而非重建浏览器。

---

### M6 · 订单观察循环无上限：1 秒一次轮询官方支付页并长期持有驱动锁（中危 / A 级）

- **状态**：待修复
- **位置**：[`railwatch_bridge.py#L951-L981`](railwatch_bridge.py#L951-L981)，配合 [`#L897`](railwatch_bridge.py#L897)、[`#L1203`](railwatch_bridge.py#L1203)

**动态实测**：3.4 秒观测内仍在运行、轮询 3 次（~1/s，符合设计），**只有 `cancel.set()` 后才退出**。

**影响**：订单停留在"待支付"时无限运行，`is_monitoring` 持续为真、驱动锁被整个任务持有，其他浏览器命令全部被拒。

**修复建议**：加退避（1s→5s→15s）+ 总时长上限，超时转 `human_action` 并释放驱动锁。

---

### M7 · `loadURL` 的 Promise 被丢弃，且无 `did-fail-load` 兜底（中危 / B 级）

- **状态**：待修复
- **位置**：[`electron/main.ts#L294`](electron/main.ts#L294)、[`#L297`](electron/main.ts#L297)

打包缺 `dist/index.html`、或 `npm run dev` 时 Vite 未就绪 ⇒ 用户只看到 `backgroundColor: "#0d1117"` 的空白深色窗口，主进程另有一条未处理的 Promise 拒绝；`electron/` 下无任何 `did-fail-load` 处理器（已 grep）。

**修复建议**：`void mainWindow.loadURL(url).catch(showLoadError)` + `webContents.on("did-fail-load", ...)`，把失败暴露到界面/托盘。

---

### M8 · 版本比较与项目内既有比较器不一致（中危 / A 级）

- **状态**：待修复
- **位置**：[`electron/updateManager.ts#L66`](electron/updateManager.ts#L66) 对比 [`electron/updateChecker.ts#L294`](electron/updateChecker.ts#L294)

**动态实测**：

```
current=0.4.2 latest=v0.4.2     -> hasUpdate=true  compareVersions=0
current=0.4.2 latest=0.4.2.0    -> hasUpdate=true  compareVersions=0
current=0.4.2 latest=0.4.2+local-> hasUpdate=true  compareVersions=0
```

`hasUpdate` 直接驱动 [`src/lib/useAppUpdate.ts#L77-L82`](src/lib/useAppUpdate.ts#L77-L82) 的 `phase: "available"/"not-available"`，进而渲染"发现新版本"或"已是最新版本"。

**修复建议**：`hasUpdate: compareVersions(currentVersion, latestVersion) < 0`，或统一以 electron-updater 的 `update-available` 事件为唯一判据。

---

### M9 · 运行时重启无退避；`runtimeContinuityUnknown` 一旦置位永不复位（中危 / B 级）

- **状态**：待修复
- **位置**：[`electron/pythonRuntime.ts#L294-L308`](electron/pythonRuntime.ts#L294-L308)、[`electron/main.ts#L342`](electron/main.ts#L342)、[`#L457-L459`](electron/main.ts#L457-L459)

`PATH` 无 python 时每秒 spawn 失败一次、每秒一个 `runtimeError` 推给渲染层，无限循环；任意一次瞬时重启都会永久置真 `runtimeContinuityUnknown`，使已下载更新只能靠完全重启应用安装。

**修复建议**：指数退避 + 最大尝试次数 + 明确的"运行时不可用"状态；该标志仅在"任务执行中崩溃"时置位，并在一次空闲探活成功后清除。

---

### M10 · `pyproject.toml` 漏登记 `railwatch_sale_times`（中危 / A 级）

- **状态**：待修复
- **位置**：[`pyproject.toml#L41-L65`](pyproject.toml#L41-L65) 对比 [`railwatch_bridge.py#L537`](railwatch_bridge.py#L537)

**动态实测**：声明 23 个 vs 磁盘 24 个运行期模块，`missing=['railwatch_sale_times']`（该文件在工作树中为**新增未提交**文件）。

**影响**：`pip install .` / sdist 安装的发行版缺该模块，`stationSaleTimes` 命令运行期抛 `ImportError`。（PyInstaller 路径会静态分析到函数内 import，打包版不受影响。）

**修复建议**：加入 `py-modules`，并加一条"根目录运行期模块均被 pyproject 覆盖"的测试防漂移。

---

### M11 · 运行时读到一行非对象 JSON 就整体退出（中危 / A 级）

- **状态**：待修复
- **位置**：[`railwatch_runtime.py#L40-L57`](railwatch_runtime.py#L40-L57)、[`#L132-L143`](railwatch_runtime.py#L132-L143)

**动态实测**（子进程）：

```
输入 "null" 行        -> exit 1 + AttributeError: 'NoneType' object has no attribute 'get'
输入非法 UTF-8 字节    -> exit 1 + UnicodeDecodeError
```

**影响**：进程带 traceback 退出 → Electron 拒绝在途请求并按 1s 重启；新进程 `_task=None`、日志/结果为空且不主动推 state，界面可能仍显示"监控中"而实际无监控。

**修复建议**：

```python
        if not isinstance(request, dict):
            self.emit_event({"event": "runtimeError", "payload": {"message": "无效请求：顶层必须为对象"}})
            return self._executor.submit(lambda: None)
```

并给读循环加 try/except、`reconfigure(encoding="utf-8", errors="replace")`。

---

### M12 · （已撤回）`check_environment` 未 `service.stop()` 会残留 ChromeDriver（D 级）

- **状态**：**已撤回，不作为问题**
- **原始怀疑**：`driver.quit()` 不停止 Service 进程，探测浏览器可能残留并占住 `chrome_profile_12306`。
- **动态实测**：
  - 已确认 selenium 4.44.0 的 `WebDriver.quit()` 源码中**没有** `service.stop()`（`Service.stop()` 仅由 `Service.__del__` 或显式调用触发）；
  - 但实测 `service.process.poll()` 在 `quit()` 后**立即返回 0**——ChromeDriver 153 在最后一个会话删除后自行退出，因此 `check_environment` 的裸 `quit()` **不会**留下进程；
  - 只有"从不 quit"的路径会留下进程（`poll()` 仍为 `None`），而该路径已被 [`_launch_chrome`](railwatch_bridge.py#L1484-L1495) 的 `except` 中的 `service.stop()` 覆盖。
- **保留建议（仅一致性，非缺陷）**：`check_environment` 改成 `try/finally` + `_dispose_driver(driver)`，与删除浏览器/退出路径统一风格。

---

### 低危问题（需修）

| 编号 | 位置 | 问题 | 修复建议 |
| --- | --- | --- | --- |
| L2 | [`railwatch_bridge.py#L1619`](railwatch_bridge.py#L1619) | `_pending_human_action` 只写不读（`#L269`/`#L854`/`#L1190` 赋值，`state_to_payload` 无该字段）；渲染层重载或运行时重启后人工接管提示丢失 | 序列化进 `state_to_payload` 或删除该字段 |
| L3 | [`railwatch_bridge.py#L837`](railwatch_bridge.py#L837)、[`#L1551-L1552`](railwatch_bridge.py#L1551-L1552) | `worker_threads` 每次启动监控追加一个 Thread，唯一清理在**从未被调用**的 `_run_worker` 中；已结束的 `Thread` 仍持有 `_target`（闭包捕获 config/task），属稳定内存滞留 | 不保留该列表，或改为定期裁剪 |
| L4 | [`gui_12306_0.py#L1046`](gui_12306_0.py#L1046)、[`#L1099-L1101`](gui_12306_0.py#L1099-L1101)、[`#L1128`](gui_12306_0.py#L1128) | `seat_col_indices` 从未写入、`_get_seat_col_index` 从未被调用（grep 确认），"席别列索引兜底"是死代码；若 `td[id^='PREFIX_']` 约定变化，所有目标席别静默读成 `None` → 永远"未命中"且无报错 | 真正填充并记录无法解析的席别，或删掉死方法让失败可见 |
| L6 | [`gui_12306_0.py#L419`](gui_12306_0.py#L419) | `urllib.request.urlopen(...).read()` 未关闭响应（仓库其他 5 处均用 `with`） | 统一 `with urllib.request.urlopen(...) as resp:` |

### 代码卫生（Low，可合并为一个清理 PR）

| 编号 | 位置 | 说明 |
| --- | --- | --- |
| L1 | [`railwatch_bridge.py#L933`](railwatch_bridge.py#L933) | `orderStage` 事件全仓库无消费者（订单状态实际靠 `state` 事件下发）→ 删除或前端补分支 |
| L5 | [`railwatch_verification.py#L39-L43`](railwatch_verification.py#L39-L43) | `verification_present`/`alternate_success_present` 仅被测试引用；若接线，`except Exception: return False` 会把"读不到页面"解释成"无需核验"（fail-open）→ 删除或改三态 |
| L7 | [`railwatch_bridge.py#L445`](railwatch_bridge.py#L445)、[`#L1075`](railwatch_bridge.py#L1075) | 日志时间戳与导出文件名用 `datetime.now()`，而调度用 `beijing_now()`；非 UTC+8 机器上日志时刻与起售时刻对不上，且无日期、跨天无法排序 |
| L8 | [`railwatch_config_contract.py#L154`](railwatch_config_contract.py#L154)、[`#L196-L208`](railwatch_config_contract.py#L196-L208) | 每个 job 继承整份顶层配置（实测 job 含 **30** 个键，序列化 2096B，含嵌套 `query_jobs`）；`config_for_persistence` 只 pop 顶层（实测两轮稳定 2096B，**不是**无界增长）→ 只合并 `TRIP_FIELD_KEYS` |
| L9 | [`src/components/VirtualEventList.tsx#L46`](src/components/VirtualEventList.tsx#L46) | `setViewport({top,height})` 每次滚动新建对象，React 无法 bail out → 每次滚动事件整列表重渲染（窗口化数学本身正确）→ 函数式更新比较后返回原 state + `React.memo` + rAF 节流 |
| L10 | [`src/store/railwatchStore.ts#L281`](src/store/railwatchStore.ts#L281) | 重复/回放 tick 时 `monitorLoops` 不更新（实测 loop=9 的重复 tick 后仍为 4）→ 把该字段移出 `accepted` 判断 |
| L11 | [`electron/updateChecker.ts#L546-L547`](electron/updateChecker.ts#L546-L547)、[`#L564-L570`](electron/updateChecker.ts#L564-L570) | 只校验 `asset.url`，`asset.name` 直接参与 `path.join`（远端可控的 `..\..\x.exe` 可逃出下载目录）；`asset.sha256` 生产代码无生产者，完整性校验实际永不执行。当前该函数仅测试引用（潜在缺陷）→ `path.basename` + 扩展名白名单，缺哈希即 fail closed |
| L12 | [`electron/alertManager.ts#L122`](electron/alertManager.ts#L122)、[`#L150`](electron/alertManager.ts#L150)；[`electron/main.ts#L100-L104`](electron/main.ts#L100-L104) | `railwatch:urgent-alert` 通道无订阅者；`railwatch:stop-alert` 是唯一无来源校验的 IPC 入口；`assertTrustedSender` 抛错却被 `ipcMain.on`（`#L377`/`#L391`/`#L399`）调用（`ipcMain.on` 的抛错不会回给渲染层，会成为主进程未捕获异常） |
| L13 | [`electron/updateManager.ts#L169`](electron/updateManager.ts#L169) | `void checkOptions.force;` —— 设置页"强制刷新"传下来的 `force` 被直接丢弃 |
| L14 | [`railwatch_orders.py#L321-L336`](railwatch_orders.py#L321-L336) | `history_detail` 取**最新** 500 条事件，却用其中最早的 `submitting` 判断 `history_complete`；事件多时误报"本地记录不完整"→ 用 `EXISTS` 单独判定 |

---

## 3. 已核实、确认不是问题的项（避免重复排查）

| 候选 | 结论 |
| --- | --- |
| `history_page` 分页游标 `rows[limit-1]` | 正是本页最后一条，配合 `(updated_at,intent_id) < (?,?)` 与降序排序语义一致——不是 off-by-one |
| `flush_telemetry` 失败后整批回插 | `connection()` 内为 `with db:`，异常整体回滚，`executemany` 不会留下部分提交行——不产生重复遥测 |
| `record_matches` 的 `prefixed` 正则 | 要求字母前缀（`[GDCZTKYSL]\d{1,5}`），票价 `927.0` 不会被当成车次 |
| `getTripDateStatus` 时区 | `todayIso()` 产出北京日历日字符串、`dayNumber()` 用 `T00:00:00Z` 解析，两端均与本地时区无关 |
| 候补截止时间只匹配相对文本 | README 明确"只接受官方实际提供且可回读确认的选项，无法匹配转人工"，属设计内 fail-closed |
| `validate_config` 顶层行程字段优先 | `tests/test_railwatch_config_contract.py:36` 显式断言，是兼容旧配置的有意设计 |
| 定时用系统时钟、HTTP `Date` 仅诊断 | `ServerTimeSync` docstring 与 `clock_source: "system"` 一致 |
| `VirtualEventList` 窗口化数学 | 前缀和、上下 padding、`first/last` 扫描均正确 |
| 渲染层 IPC 监听器泄漏 | `App.tsx:351-384`、`useAppUpdate`、`useClock`、`useBeijingToday`、`useSidebarPreference`、`useThemePreference` 清理与依赖均正确 |
| `gui:580` 的 `raise A if c else B`、速率限制器突发重试/衰减 | 语义正确 / 有测试断言 |
| `build/lib/` 旧副本 | `.gitignore` 第 12 行已忽略 `/build/` |
| `selenium==4.44.0`、`requests==2.33.1` | 本机已安装同版本，依赖固定值有效 |
| **M12 驱动残留** | 见上文：ChromeDriver 在 `quit()` 后自行退出，**已撤回** |

---

## 4. 修复计划与验收标准

### 4.1 建议顺序（每步都在绿色基线上做）

| 顺序 | 项 | 改动量 | 验收标准 |
| --- | --- | --- | --- |
| 1 | **C1** 确认回执三态化 | 小（单函数） | 新增 fixture 用例：未送达 → 返回 `None`、无 dispatched 标记、`confirmClicks` 不增长、不导航 |
| 2 | **H1** stale 处理 | 小 | 新增 fixture 用例：重渲染后不误报"未命中"；`find_button` 对过期元素安全返回 |
| 3 | **H2** 订单列表正向证据 | 中（JS + Python + fixture） | 新增 4 场景用例：class 改名与竞态均**不**产生 `not_submitted`；`unresolved` 不被释放 |
| 4 | **H4** phase 映射 + **M10** pyproject | 很小 | H4：订单阶段收尾后 phase 与 monitoring 一致；M10：新增"pyproject 覆盖全部运行期模块"测试 |
| 5 | **M1 / M4 / M6 / M11** | 中 | M1：配置变更后响应必须留下可见错误；M4：`task_activity()` 在慢脚本期间不被阻塞；M6：观察循环有退避与上限；M11：非对象行不退出进程 |
| 6 | **M3 / M2** 性能 | 中 | M3：单位时间往返数下降（目标 ≤ 10 次/秒）；M2：每条日志处理成本从 5 趟降为 1 趟 |
| 7 | **M5 / M7 / M8 / M9 / H3** | 中 | 逐项加断言（见各条"回归测试"） |
| 8 | 其余 Low 与代码卫生 | 小 | 合并为 1–2 个清理 PR |

### 4.2 回归基线（每个 PR 至少跑）

```powershell
python -X utf8 -m unittest discover -s tests -p "test_*.py"   # 当前 312 passed
python -X utf8 tests/order_browser_smoke.py                   # 订单页真实浏览器回归
python -X utf8 tests/browser_smoke.py                         # 查询页真实浏览器回归
npm test                                                      # 当前 188 renderer passed + electron 套件
npm run build                                                 # 类型检查 + 主进程/渲染层构建
```

---

## 附录 A · 动态验证证据原文（节选）

```
# C1 真实性（真 Chrome + tests/fixtures/orders.html）
F1  returned=True  fixture.confirmClicks 0 -> 0 (12306 never processed a confirm)
F2  marks=['regular_confirm_attempt'] -> 无 'regular_confirm_dispatched'，无日志，返回值真值化
F3  confirmed_clicked=True -> _post_submit navigated to ['https://kyfw.12306.cn/otn/view/train_order.html']
C1/real-a  弹窗仍可见 -> status='verification' navigations=[]（优雅分支）
C1/real-c  confirmed_clicked=False -> 不额外导航

# H1 真实性（真 Chrome + 真 WebElement）
H1/real-a  fresh snapshot           -> hit=('G101', '二等座', '有')
H1/real-b  结果表重渲染后           -> hit=None（DOM 仍显示 有）
H1/real-c  同一 DOM 重新 snapshot    -> hit=('G101', '二等座', '有')
H1c        find_button 让 StaleElementReferenceException 逃逸

# H2 真实性（真 Chrome 执行真实 SNAPSHOT_JS → 真实 OrderPage.result）
H2/control .order-item            orders=1 pendingEmpty=False -> 'pending_payment' order_id='E123456'
H2a        仅行 class 改名         orders=0 pendingEmpty=True  -> 'not_submitted' no_order=True
H2b        相隔 1.2s              early: not_submitted | late: pending_payment
H2c        写入真实 SQLite         pending()=None（唯一索引闸门释放）

# H3 确认门（ipcSecurity 单测）
startMonitor {confirmed:true} -> null（无弹窗）；无 confirmed -> 确认自动化
clearLocalData / closeBrowser / dismissOrder with confirmed=true -> 仍弹窗

# H4 phase 映射
task.done.set() + _transition(task,'pending_payment') -> phase='monitoring' monitoring=False

# M1 手动查询丢弃（renderer store 单测）
改配置后 manualQueryId=null pending=false views=0 error=null
req-1 回包后 results=0 views=0 error=null；对照 results=1 views=1

# M2 事件面板成本（1000 条，25 次中位）
单趟 0.33ms；EventPanel 工作量 1.74ms = 5.26×；冷启 5 趟 6.5ms；20 条/秒 ≈ 35ms/s

# M3 查询轮询开销（计数包装真驱动）
2.00s 内 54 次 execute_script = 27.0/s → 默认 40s 预算 ≈ 1080 次往返/轮

# M4 锁竞争（隔离测量）
2.0s execute_script 期间：task_activity() 阻塞 1.75s；stop_monitor() 阻塞 >0.5s

# M6 订单观察循环
3.4s 仍在运行、轮询 3 次（~1/s）；仅 cancel.set() 后退出

# M8 版本比较（updateManager 单测）
0.4.2 vs v0.4.2 / 0.4.2.0 / 0.4.2+local -> hasUpdate=true，compareVersions=0

# M10 打包清单
声明 23 个 vs 磁盘 24 个运行期模块；missing=['railwatch_sale_times']

# M11 stdin 健壮性（子进程）
"null" 行 -> exit 1 + AttributeError；非法 UTF-8 字节 -> exit 1 + UnicodeDecodeError

# M12 撤回依据（selenium 4.44.0 + ChromeDriver 153）
before quit: service.process.poll() = None
after  quit: service.process.poll() = 0        ← 子进程自行退出，无残留
从不 quit:    service.process.poll() = None     ← 该路径已被 _launch_chrome 的 service.stop() 覆盖
```

## 附录 B · 复现命令

```powershell
$env:PYTHONPATH='D:\Pycharm Project\sucess_12306'
$env:PYTHONUTF8='1'

# 基线
python -X utf8 -m unittest discover -s tests -p "test_*.py"
npm test

# 探针（位于 %TEMP%\rw-verify\，不写入仓库）
python -X utf8 "$env:TEMP\rw-verify\probe_a.py"    # C1 控制流 / H1 单测 / H2 链 / H4 / L8
python -X utf8 "$env:TEMP\rw-verify\probe_b.py"    # H1 修正版 / M11 stdin / M12 selenium 源码 / M10
python -X utf8 "$env:TEMP\rw-verify\probe_c2.py"   # H2 真浏览器（对照 / class 改名 / 竞态 / DB 闸门）
python -X utf8 "$env:TEMP\rw-verify\probe_d.py"    # H1 + C1 真 DOM
python -X utf8 "$env:TEMP\rw-verify\probe_e.py"    # M6 / M4 / M10
python -X utf8 "$env:TEMP\rw-verify\probe_f.py"    # C1 真实页面假成功 + 导航
```

渲染层与主进程探针为临时 vitest 文件（`src/store/__probe__.test.ts`、`electron/__probe__.test.ts`），验证后已删除，未留在仓库中。

## 附录 C · 仍需线上验收的部分（C 级）

1. **H2 触发前提**：已用真浏览器证实"仅改 class 名 / 1.2 秒渲染窗口即可 fail-open"，但官方订单页是否会出现该窗口需一次真实账号验收（建议：下单后在"未完成订单"页刷新并抓取 `SNAPSHOT_JS` 输出）。
2. **站名粘连脆弱性**（新发现，Low）：真机实测 `contains_token("…北京站…", "北京")` 为 **False**（尾边界禁止后随 CJK），而 checkout 分支通过 `form_token(..., "站")` 容忍 站 后缀；仓库自带订单 fixture 使用 `北京 上海`（不粘连）格式，故当前不触发。若线上订单列表渲染"北京站"，`record_matches` 会静默失配 → 已存在订单被报为"结果未知"。建议线上核对一次订单列表文本形态。
3. **候补截止时间**：维持"设计内 fail-closed"，如需支持绝对时间选项，按 [`railwatch_order_page.py#L430-L461`](railwatch_order_page.py#L430-L461) 归一化为绝对时刻后再比较。
