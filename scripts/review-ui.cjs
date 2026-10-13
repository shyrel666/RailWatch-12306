const { chromium } = require(process.env.RAILWATCH_PLAYWRIGHT || "playwright");
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const output = path.resolve("build/ui-review");
fs.mkdirSync(output, { recursive: true });
(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.RAILWATCH_CHROME_PATH ? { executablePath: process.env.RAILWATCH_CHROME_PATH } : { channel: "chrome" }) });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
  });
  const errors = [];
  const navigate = name => page.locator(".sidebar").getByRole("button", { name, exact: true }).click();
  page.on("pageerror", (error) => errors.push(error.message));
  await page.addInitScript(() => {
    window.__commands = [];
    window.__pendingConfirm = new Map();
    window.__eventListeners = new Set();
    const state = {
      phase: "idle", environment_ready: false, login_ready: false, query_ready: false, monitoring: false,
      auto_submit_enabled: false, auto_alternate_enabled: false, risk_level: "notice",
      status_message: "就绪", error_message: "", current_config: {}, hits: [], summary: "就绪",
    };
    const runs = [
      { run_id: "review-immediate", started_at: Date.now() / 1000 - 600, target_at: null, conclusion: "已停止",
        trip: { from_station: "北京", to_station: "上海" } },
      { run_id: "review-timed", started_at: Date.now() / 1000 - 300, target_at: Date.now() / 1000 - 120,
        conclusion: "需要人工处理", trip: { from_station: "广州", to_station: "长沙" } },
    ];
    const preferences = { theme: "light", close_to_tray: false, auto_rehearsal: false, notification_settings: {} };
    window.railwatch = {
      command: async (command, payload = {}) => {
        window.__commands.push({ command, payload });
        if (command === "loadPreferences") return { ...preferences };
        if (command === "savePreferences") return Object.assign(preferences, payload);
        if (command === "rehearsalHistory") return { items: [] };
        if (command === "queryPulse") return { run_id: null, started_at: null, target_at: null,
          trip: {}, recorded: 0, items: [], active: false };
        if (command === "runReviews") return { items: runs, next_cursor: null };
        if (command === "runReview") return { ...runs.find(run => run.run_id === payload.run_id),
          segments: [], prediction: [], slowest: null, preparation_margin_ms: null,
          query_median_ms: null, history_complete: true, note: "本地界面测试数据" };
        if (command === "checkEnvironment") return new Promise(resolve => {
          window.__finishEnvironmentCheck = () => {
            state.environment_ready = true;
            resolve({ ...state });
          };
        });
        if (command === "checkLogin") return { ...state, phase: "error", risk_level: "warning",
          status_message: "请先打开登录页。", error_message: "请先打开登录页。" };
        if (command === "loadTripState") return { saved_config: await window.railwatch.command("loadConfig"),
          saved_at: Date.now() / 1000, draft: { status: "missing", draft: null, warning: null } };
        if (command === "loadTripChoices") return { recent_routes: [], favorites: [] };
        if (command === "searchStations") return { items: [], warning: null };
        if (command === "orderHistory") return { items: [], next_cursor: null };
        if (command === "loadConfig")
          return {
            from_station_cn: "北京",
            to_station_cn: "上海",
            date: new Intl.DateTimeFormat("en-CA", {
              timeZone: "Asia/Shanghai",
              year: "numeric",
              month: "2-digit",
              day: "2-digit",
            }).format(new Date(Date.now() + 3 * 86400000)),
            date_range: "单日",
            passengers: "张三",
            passenger_count: 1,
            interval: 5,
            query_timeout: 40,
            train_code: "G101, G103",
            seat_keyword: "二等座",
            seat_prefer: "无偏好",
            smart_rate: true,
            keep_alive: true,
            auto_submit: false,
            auto_alternate: false,
            timer_enabled: false,
            target_time: "08:00:00",
            sale_at: "",
            alternate_deadline: "开车前60分钟",
            prepare_time: 2,
          };
        if (command === "getRuntimeInfo")
          return {
            app_display_name: "RailWatch 12306",
            app_version: "0.4.2",
            data_dir: "C:/Users/Demo/AppData/Local/railwatch-12306",
            data_dir_writable: true,
            data_dir_free_bytes: 28250000000,
            chrome_version: "Chrome 148",
            chromedriver_path: "C:/RailWatch/driver/chromedriver.exe",
            core_available: true,
            seat_capabilities: [{ name: "二等座", query: true, regular: true, alternate: true }],
            selenium_available: true,
            chromedriver_manager_available: true,
            network_ok: true,
            network_label: "正常",
            railway_ok: true,
            railway_label: "正常",
            state: { ...state },
          };
        return {};
      },
      onEvent: listener => { window.__eventListeners.add(listener); return () => window.__eventListeners.delete(listener); },
      onConfirmRequest: (callback) => { window.__confirmRequest = callback; return () => { window.__confirmRequest = null; }; },
      respondConfirmation: (id, accepted) => {
        window.__commands.push({ command: "respondConfirmation", id, accepted });
        window.__pendingConfirm.get(id)?.(accepted);
        window.__pendingConfirm.delete(id);
      },
      stageDraft: () => {},
      onUpdateState: () => () => {},
      stopUrgentAlert: () => {},
      getUpdateState: async () => ({
        phase: "not-available",
        currentVersion: "0.4.2",
      }),
      checkUpdate: async () => ({
        ok: true,
        currentVersion: "0.4.2",
        latestVersion: "0.4.2",
        hasUpdate: false,
      }),
      getAppInfo: async () => ({
        electronVersion: "39.2.7",
        chromeVersion: "142",
        nodeVersion: "22",
        appVersion: "0.4.2",
      }),
      openExternal: async () => ({ ok: true }),
      getExportLocations: async () => ({ directory: "C:/RailWatch/logs", fileName: "railwatch-events.txt", shortcuts: [{ name: "下载", path: "C:/Downloads" }] }),
      listExportDirectory: async directory => ({ directory, parent: "C:/", folders: [{ name: "历史记录", path: `${directory}/archive` }], files: ["previous-events.txt"] }),
      prepareLogExport: async (directory, fileName) => {
        if (fileName === "previous-events.txt") {
          const accepted = await new Promise(resolve => {
            window.__pendingConfirm.set("export-overwrite", resolve);
            window.__confirmRequest({ id: "export-overwrite", title: "替换已有日志文件？",
              message: `该文件已存在：\n${directory}/${fileName}\n\n替换后，原文件内容将被覆盖。`,
              okText: "替换文件", cancelText: "保留原文件", danger: true });
          });
          if (!accepted) return null;
        }
        return `${directory}/${fileName}`;
      },
    };
  });
  await page.goto(process.env.RAILWATCH_PREVIEW_URL || "http://127.0.0.1:5173");
  await page.getByRole("heading", { name: "仪表盘", exact: true }).waitFor();
  await page.waitForTimeout(800);
  await page.screenshot({ path: path.join(output, "dashboard-light.png") });
  const switchTheme = async (value) => {
    const control = page
      .getByRole("radiogroup", { name: "外观主题" })
      .getByRole("radio", { name: value });
    for (let attempt = 0; attempt < 3; attempt++) {
      if ((await control.getAttribute("aria-checked")) === "true") break;
      await control.click();
    }
    if ((await control.getAttribute("aria-checked")) !== "true")
      throw new Error("Theme did not switch to " + value);
    await page.waitForTimeout(250);
  };
  await switchTheme("深色");
  await page.screenshot({ path: path.join(output, "dashboard-dark.png") });
  await switchTheme("明亮");
  const measurements = [];
  const interactions = [];
  for (const [width, height] of [
    [1180, 720],
    [1440, 900],
    [1920, 1080],
  ]) {
    await page.setViewportSize({ width, height });
    for (const theme of ["明亮", "深色"]) {
      await switchTheme(theme);
      for (const name of [
        "仪表盘",
        "行程设置",
        "购票监控",
        "订单中心",
        "运行复盘",
        "系统设置",
        "关于",
      ]) {
        await navigate(name);
        await page.mouse.move(1150, 8);
        await page.waitForTimeout(350);
        if (name === "仪表盘" && (
          await page.getByLabel("自动化状态").count() ||
          await page.getByRole("button", { name: /配置自动化/ }).count()
        ))
          throw new Error("Dashboard still exposes automation configuration");
        if (name === "仪表盘") {
          assert.equal(await page.getByRole("region", { name: "查询脉搏" })
            .getByRole("button", { name: "运行复盘" }).count(), 0, "Query pulse still exposes the removed review link");
          assert.equal(await page.getByRole("region", { name: "近 14 天运行" })
            .getByRole("button", { name: "运行复盘" }).count(), 1, "Run history lost its review link");
        }
        if (name === "购票监控")
          assert.equal(await page.getByText("调整自动化", { exact: true }).count(), 0, "Removed automation link is visible");
        if (name === "运行复盘") {
          await page.getByRole("article", { name: "复盘详情" }).waitFor();
          assert.equal(await page.getByText("查看复盘", { exact: true }).count(), 0, "Removed review label is visible");
          assert.equal(await page.getByText(/记录即时与定时监控的执行阶段/).count(), 0, "Removed review description is visible");
          const offsets = await page.locator(".rv-run").evaluateAll(cards => cards.map(card => {
            const box = card.getBoundingClientRect(), time = card.querySelector("time").getBoundingClientRect();
            return Math.abs((box.top + box.bottom - time.top - time.bottom) / 2);
          }));
          assert.equal(offsets.length, 2, "Review fixture cards are missing");
          assert.ok(offsets.every(offset => offset <= 1), `Review times are off center: ${offsets}`);
          interactions.push({ scenario: "review-time-centering", width, height, theme, offsets });
        }
        const layout = await page.evaluate(() => {
          const root = document.querySelector(".app-shell");
          const content = document.querySelector(".page-surface");
          const footer = document.querySelector(".trip-setup-footer");
          return {
            rootWidth: root.scrollWidth,
            viewportWidth: innerWidth,
            contentWidth: content.scrollWidth,
            visibleWidth: content.clientWidth,
            footerBottom: footer?.getBoundingClientRect().bottom,
            viewportHeight: innerHeight,
          };
        });
        measurements.push({ width, height, theme, name, ...layout });
        if (
          layout.rootWidth > width ||
          layout.contentWidth > layout.visibleWidth + 1 ||
          (layout.footerBottom && layout.footerBottom > height - 8)
        )
          throw new Error(
            "Layout overflow: " + JSON.stringify(measurements.at(-1)),
          );
        await page.screenshot({
          path: path.join(
            output,
            width +
              "-" +
              (theme === "明亮" ? "light" : "dark") +
              "-" +
              {
                仪表盘: "dashboard",
                行程设置: "trip",
                购票监控: "monitor",
                订单中心: "orders",
                运行复盘: "reviews",
                系统设置: "settings",
                关于: "about",
              }[name] +
              ".png",
          ),
        });
      }
    }
  }
  await page.setViewportSize({ width: 1440, height: 900 });

  for (const theme of ["明亮", "深色"]) {
    await switchTheme(theme);
    await page.evaluate(async () => {
      const { railwatchStore, defaultStatus } = await import("/src/store/railwatchStore.ts");
      railwatchStore.setState({ status: { ...defaultStatus }, lastHumanAction: null });
      delete window.__finishEnvironmentCheck;
    });
    await navigate("系统设置");
    const login = page.getByRole("button", { name: "检查登录", exact: true });
    assert.equal(await login.isEnabled(), false, "Login check is enabled before the environment check");
    assert.equal(await page.getByRole("button", { name: /打开登录/ }).isEnabled(), false);
    // Replay the old login-before-environment response to verify recovery guidance.
    await page.evaluate(async () => {
      const { defaultStatus } = await import("/src/store/railwatchStore.ts");
      window.__eventListeners.forEach(listener => listener({ event: "state", payload: {
        ...defaultStatus, phase: "error", risk_level: "warning",
        status_message: "请先打开登录页。", error_message: "请先打开登录页。",
      } }));
    });
    await navigate("仪表盘");
    await page.getByText("等待环境检查", { exact: true }).waitFor();
    assert.equal(await page.getByRole("button", { name: "查看运行详情" }).count(), 0);
    await page.getByRole("button", { name: "检查环境", exact: true }).click();
    await page.waitForFunction(() => typeof window.__finishEnvironmentCheck === "function");
    assert.equal(await login.isEnabled(), false, "Login check is enabled while the environment check is pending");
    const notice = page.locator(".railwatch-environment-success");
    assert.equal(await notice.count(), 0, "Success was shown before the environment check finished");
    await page.evaluate(() => window.__finishEnvironmentCheck());
    await notice.waitFor();
    assert.equal(await notice.textContent(), "环境检查完成，运行环境已就绪。");
    const colors = await notice.evaluate(element => {
      const reference = document.createElement("i");
      reference.style.color = "var(--success)";
      reference.style.backgroundColor = "var(--success-soft)";
      document.body.append(reference);
      const actual = getComputedStyle(element), expected = getComputedStyle(reference);
      const result = { foreground: actual.color, background: actual.backgroundColor,
        border: actual.borderTopColor, expectedForeground: expected.color, expectedBackground: expected.backgroundColor };
      reference.remove();
      return result;
    });
    assert.equal(colors.foreground, colors.expectedForeground);
    assert.equal(colors.background, colors.expectedBackground);
    assert.equal(colors.border, colors.expectedForeground);
    await page.waitForTimeout(300); // Capture after the notice entrance animation.
    const noticeBox = await notice.boundingBox();
    assert.ok(noticeBox && noticeBox.y >= 0 && noticeBox.y + noticeBox.height <= 900, "Success popup is clipped");
    await page.screenshot({ path: path.join(output, `environment-success-${theme === "明亮" ? "light" : "dark"}.png`) });
    await notice.waitFor({ state: "hidden", timeout: 5000 });
    assert.equal(await login.isEnabled(), true);
    await login.click();
    await page.waitForFunction(() => window.__commands.some(item => item.command === "checkLogin"));
    await navigate("仪表盘");
    await page.getByRole("button", { name: "前往登录", exact: true }).waitFor();
    await page.getByText("等待登录", { exact: true }).waitFor();
    assert.equal(await page.getByRole("button", { name: "查看运行详情" }).count(), 0);
    interactions.push({ scenario: "environment-success-and-login-guidance", theme, colors });
  }

  await navigate("运行复盘");
  await page.getByRole("heading", { name: "北京 → 上海", exact: true }).waitFor();
  for (const [index, target] of [[1, "route"], [0, "time"], [1, "padding"], [0, "card"], [1, "Enter"], [0, "Space"]]) {
    const card = page.locator(".rv-run").nth(index);
    const before = await page.evaluate(() => window.__commands.filter(item => item.command === "runReview").length);
    if (target === "Enter" || target === "Space") {
      await card.focus();
      await card.press(target);
    } else if (target === "padding") {
      await card.click({ position: { x: 6, y: 6 } });
    } else if (target === "card") {
      await card.click();
    } else {
      await card.locator(target === "route" ? ".rv-run-trip" : "time").click();
    }
    await page.getByRole("heading", { name: index === 0 ? "北京 → 上海" : "广州 → 长沙", exact: true }).waitFor();
    assert.equal(await card.getAttribute("aria-pressed"), "true");
    assert.equal(await page.locator(".rv-run[aria-pressed=true]").count(), 1);
    const after = await page.evaluate(() => window.__commands.filter(item => item.command === "runReview").length);
    assert.equal(after - before, 1, `${target} sent duplicate review requests`);
    interactions.push({ scenario: "review-card-open", target });
  }
  await navigate("仪表盘");
  await page.evaluate(async () => {
    const { railwatchStore, defaultStatus, defaultConfig } = await import(
      "/src/store/railwatchStore.ts"
    );
    const task = {
      run_id: "preview",
      status: "backoff",
      started_at: Date.now() / 1000 - 85,
      next_query_at: Date.now() / 1000 + 7,
    };
    railwatchStore.setState({
      status: {
        ...defaultStatus,
        monitoring: true,
        environment_ready: true,
        login_ready: true,
        query_ready: true,
        status_message: "正在关注目标车次的余票变化",
        task,
        current_config: railwatchStore.getState().config,
      },
      monitorLoops: 18,
      results: [
        {
          train: "G101",
          raw: "北京南 → 上海虹桥 · 07:00 — 12:38 · 二等座：无 · 一等座：候补",
        },
        { train: "G103", raw: "北京南 → 上海虹桥 · 二等座：有票" },
      ],
      hits: [
        {
          train_code: "G103",
          seat_type: "二等座",
          label: "发现符合条件的余票",
          status: "有票",
          source: "query",
          detail: "请在官方页面核对余票与订单",
        },
      ],
    });
    railwatchStore.getState().applyLog({
      level: "INFO",
      time: "08:00:00",
      message: "监控已启动：正在查询目标车次",
    });
    railwatchStore.getState().applyLog({
      level: "WARN",
      time: "08:00:07",
      message: "请核对订单：等待你在官方页面继续处理",
    });
  });
  await navigate("购票监控");
  await page.screenshot({
    path: path.join(output, "monitor-running-dark.png"),
  });
  await page.evaluate(async () => {
    const { railwatchStore } = await import("/src/store/railwatchStore.ts");
    railwatchStore.setState({
      status: {
        ...railwatchStore.getState().status,
        monitoring: false,
        order: {
          status: "pending_payment",
          label: "预订待支付",
          reason: "请在官方页面完成支付。",
        },
      },
      lastHumanAction: {
        title: "需要你完成支付",
        message: "打开官方订单页面核对车次、乘客与金额。",
      },
    });
  });
  await navigate("仪表盘");
  await page.getByRole("button", { name: "查看并处理订单" }).click();
  await page.screenshot({
    path: path.join(output, "monitor-attention-dark.png"),
  });
  await page.getByRole("button", { name: "显示事件日志" }).click();
  await page.getByRole("dialog").waitFor();
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(output, "log-drawer-dark.png") });
  await page.getByRole("tab", { name: /警告/ }).click();
  await page.keyboard.press("Escape");
  await page.getByRole("dialog").waitFor({ state: "hidden" });
  if (
    !(await page
      .getByRole("button", { name: "显示事件日志" })
      .evaluate((el) => el === document.activeElement))
  )
    throw new Error("Drawer focus was not restored");
  await page.getByRole("button", { name: "显示事件日志" }).click();
  if (
    (await page
      .getByRole("tab", { name: /警告/ })
      .getAttribute("aria-selected")) !== "true"
  )
    throw new Error("Log filter not retained");
  await page.keyboard.press("Escape");
  await page.getByRole("dialog").waitFor({ state: "hidden" });
  await navigate("行程设置");
  await page.locator("#trip-automation[open]").waitFor();
  await page.getByRole("switch", { name: /自动提交已关闭/ }).click();
  await page.locator(".railwatch-dialog").waitFor();
  await page.waitForTimeout(400);
  await page.screenshot({
    path: path.join(output, "automation-confirmation-dark.png"),
  });
  await page.getByRole("button", { name: /取\s*消/ }).click();
  if (
    (await page
      .getByRole("switch", { name: /自动提交已关闭/ })
      .getAttribute("aria-checked")) !== "false"
  )
    throw new Error("Automation enabled despite cancellation");
  await page.locator(".railwatch-dialog").waitFor({ state: "hidden" });
  if (await page.locator("#trip-automation").getByRole("button", { name: "配置", exact: true }).count())
    throw new Error("Automation configuration available despite cancelled activation");
  // Stress the smallest usable renderer, including space occupied by a native title bar.
  await page.setViewportSize({ width: 1180, height: 688 });
  for (const theme of ["明亮", "深色"]) {
    await switchTheme(theme);
    await page.evaluate(async () => {
      const { railwatchStore, defaultStatus } = await import(
        "/src/store/railwatchStore.ts"
      );
      railwatchStore.setState({
        status: {
          ...defaultStatus,
          phase: "error",
          error_message: "浏览器连接中断，请检查本机环境后重试。",
        },
        lastHumanAction: null,
        config: {
          ...railwatchStore.getState().config,
          train_code: Array.from(
            { length: 80 },
            (_, i) => "G" + (100 + i),
          ).join(", "),
          passengers: "测试乘客甲，测试乘客乙，测试乘客丙",
        },
        results: [{ train: "G101", raw: "详细查询结果 · ".repeat(50) }],
      });
    });
    for (const name of ["仪表盘", "行程设置", "购票监控", "订单中心", "运行复盘", "系统设置"]) {
      await navigate(name);
      if (name === "行程设置") {
        for (const id of ["trip-query", "trip-timer"]) {
          await page.locator("#" + id + " > summary").click();
        }
      }
      await page.mouse.move(1100, 8);
      await page.waitForTimeout(250);
      const overflow = await page.evaluate(() => {
        const content = document.querySelector(".page-surface");
        const footer = document.querySelector(".trip-setup-footer");
        const form = document.querySelector(".trip-setup-form-scroll");
        return (
          content.scrollWidth > content.clientWidth + 1 ||
          (form && form.scrollWidth > form.clientWidth + 1) ||
          (footer && footer.getBoundingClientRect().bottom > innerHeight - 8)
        );
      });
      if (overflow)
        throw new Error("Long-content overflow: " + name + " / " + theme);
      await page.screenshot({
        path: path.join(
          output,
          "stress-" +
            (theme === "明亮" ? "light" : "dark") +
            "-" +
            {
              仪表盘: "dashboard",
              行程设置: "trip",
              购票监控: "monitor",
              订单中心: "orders",
              运行复盘: "reviews",
              系统设置: "settings",
            }[name] +
            ".png",
        ),
      });
    }
  }

  await page.setViewportSize({ width: 1440, height: 900 });
  let nativeDialogs = 0;
  page.on("dialog", async dialog => { nativeDialogs++; await dialog.dismiss(); });
  for (const theme of ["明亮", "深色"]) {
    await switchTheme(theme);
    const suffix = theme === "明亮" ? "light" : "dark";
    await page.evaluate(() => window.__confirmRequest({ id: "exit-check", title: "无法安全退出",
      message: "退出未完成：任务停止超时。\n\n强制退出将终止本应用运行时，任务最终状态无法确认。退出不会取消官方订单，请在官方页面核对和支付。",
      okText: "强制退出", cancelText: "取消", danger: true }));
    let dialog = page.getByRole("dialog");
    await dialog.waitFor();
    await page.waitForTimeout(300);
    if (!(await page.evaluate(() => document.activeElement?.textContent?.replace(/\s/g, "").includes("取消"))))
      throw new Error("Exit prompt must default to cancellation");
    await page.screenshot({ path: path.join(output, `exit-dialog-${suffix}.png`) });
    await page.keyboard.press("Escape");
    await dialog.waitFor({ state: "hidden" });
    if (!(await page.evaluate(() => window.__commands.some(item => item.id === "exit-check" && item.accepted === false))))
      throw new Error("Escape did not decline the exit");
    await page.evaluate(() => window.__confirmRequest({ id: "tray-check", title: "已启用关闭到托盘",
      message: "关闭窗口后 RailWatch 会在托盘继续运行。\n双击托盘图标可重新打开。", kind: "info", okText: "知道了" }));
    dialog = page.getByRole("dialog");
    await dialog.waitFor();
    if (await dialog.getByRole("button", { name: /取\s*消/ }).count()) throw new Error("Tray notice should only have acknowledgement");
    await dialog.getByRole("button", { name: "知道了" }).click();
    await dialog.waitFor({ state: "hidden" });
    await page.getByRole("button", { name: "显示事件日志" }).click();
    await page.getByRole("button", { name: "导出日志", exact: true }).click();
    const picker = page.getByRole("dialog", { name: "导出事件日志" });
    await picker.waitFor();
    await picker.getByRole("button", { name: /历史记录/ }).click();
    await page.waitForTimeout(300);
    await page.screenshot({ path: path.join(output, `export-dialog-${suffix}.png`) });
    await picker.getByRole("button", { name: /previous-events.txt/ }).click();
    await picker.getByRole("button", { name: "导出日志", exact: true }).click();
    const overwrite = page.getByRole("dialog", { name: "替换已有日志文件？" });
    await overwrite.waitFor();
    await overwrite.getByRole("button", { name: "保留原文件" }).click();
    await overwrite.waitFor({ state: "hidden" });
    await picker.getByRole("button", { name: /取\s*消/ }).click();
    await picker.waitFor({ state: "hidden" });
    // The picker returns focus to the drawer after its close animation; Escape only reaches the drawer then.
    await page.waitForFunction(() => document.querySelector(".log-drawer")?.contains(document.activeElement));
    await page.keyboard.press("Escape");
    await page.getByRole("dialog").waitFor({ state: "hidden" });
  }
  if (nativeDialogs) throw new Error("A native browser dialog was opened");

  const commands = await page.evaluate(() => window.__commands);
  fs.writeFileSync(
    path.join(output, "report.json"),
    JSON.stringify({ measurements, interactions, errors, commands }, null, 2),
  );
  await browser.close();
  if (errors.length) throw new Error(errors.join("\n"));
  console.log(
    "UI review passed: " +
      measurements.length +
      " page/theme/viewport combinations; environment notifications, review cards, removed links, logs and confirmation verified. Screenshots: " +
      output,
  );
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
