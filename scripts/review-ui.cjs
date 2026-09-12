const { chromium } = require(process.env.RAILWATCH_PLAYWRIGHT || "playwright");
const fs = require("node:fs");
const path = require("node:path");
const output = path.resolve("build/ui-review");
fs.mkdirSync(output, { recursive: true });
(async () => {
  const browser = await chromium.launch({ headless: true, channel: "chrome" });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
  });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.addInitScript(() => {
    window.__commands = [];
    window.railwatch = {
      command: async (command, payload) => {
        window.__commands.push({ command, payload });
        if (command === "loadPreferences") return { theme: "light" };
        if (command === "savePreferences") return { theme: payload.theme };
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
            app_version: "0.3.2",
            data_dir: "C:/Users/Demo/AppData/Local/railwatch-12306",
            data_dir_writable: true,
            data_dir_free_bytes: 28250000000,
            chrome_version: "Chrome 148",
            chromedriver_path: "C:/RailWatch/driver/chromedriver.exe",
            core_available: true,
            selenium_available: true,
            chromedriver_manager_available: true,
            network_ok: true,
            network_label: "正常",
            railway_ok: true,
            railway_label: "正常",
            state: {
              phase: "idle",
              environment_ready: false,
              login_ready: false,
              query_ready: false,
              monitoring: false,
              auto_submit_enabled: false,
              auto_alternate_enabled: false,
              risk_level: "notice",
              status_message: "就绪",
              error_message: "",
              current_config: {},
              hits: [],
              summary: "就绪",
            },
          };
        return {};
      },
      onEvent: () => () => {},
      onUpdateState: () => () => {},
      stopUrgentAlert: () => {},
      getUpdateState: async () => ({
        phase: "not-available",
        currentVersion: "0.3.2",
      }),
      checkUpdate: async () => ({
        ok: true,
        currentVersion: "0.3.2",
        latestVersion: "0.3.2",
        hasUpdate: false,
      }),
      getAppInfo: async () => ({
        electronVersion: "39.2.7",
        chromeVersion: "142",
        nodeVersion: "22",
        appVersion: "0.3.2",
      }),
      openExternal: async () => ({ ok: true }),
      showSaveDialog: async () => null,
    };
  });
  await page.goto(process.env.RAILWATCH_PREVIEW_URL || "http://127.0.0.1:5173");
  await page.getByRole("heading", { name: "仪表盘", exact: true }).waitFor();
  await page.waitForTimeout(800);
  await page.screenshot({ path: path.join(output, "dashboard-light.png") });
  const switchTheme = async (value) => {
    const control = page.getByRole("button", { name: /外观主题/ }).first();
    for (let attempt = 0; attempt < 3; attempt++) {
      if ((await control.textContent()).trim() === value) break;
      await control.click();
    }
    if ((await control.textContent()).trim() !== value)
      throw new Error("Theme did not switch to " + value);
    await page.waitForTimeout(250);
  };
  await switchTheme("深色");
  await page.screenshot({ path: path.join(output, "dashboard-dark.png") });
  await switchTheme("明亮");
  const measurements = [];
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
        "系统设置",
        "关于",
      ]) {
        await page.getByRole("button", { name, exact: true }).click();
        await page.mouse.move(1150, 8);
        await page.waitForTimeout(350);
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
          (layout.footerBottom && layout.footerBottom > height - 31)
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
  await page.getByRole("button", { name: "仪表盘", exact: true }).click();
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
  await page.getByRole("button", { name: "购票监控", exact: true }).click();
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
  await page.getByRole("button", { name: "仪表盘", exact: true }).click();
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
  await page.getByRole("button", { name: "仪表盘", exact: true }).click();
  await page.getByRole("button", { name: /配置自动化/ }).click();
  if (!(await page.locator("#trip-automation").evaluate((el) => el.open)))
    throw new Error("Automation section did not open");
  await page.getByRole("switch", { name: /自动提交关闭/ }).click();
  await page.getByRole("dialog").waitFor();
  await page.waitForTimeout(400);
  await page.screenshot({
    path: path.join(output, "automation-confirmation-dark.png"),
  });
  await page.getByRole("button", { name: /取\s*消/ }).click();
  if (
    (await page
      .getByRole("switch", { name: /自动提交关闭/ })
      .getAttribute("aria-checked")) !== "false"
  )
    throw new Error("Automation enabled despite cancellation");
  await page.getByRole("dialog").waitFor({ state: "hidden" });
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
    for (const name of ["仪表盘", "行程设置", "购票监控", "系统设置"]) {
      await page.getByRole("button", { name, exact: true }).click();
      if (name === "行程设置") {
        for (const id of ["trip-query", "trip-timer", "trip-automation"]) {
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
          (footer && footer.getBoundingClientRect().bottom > innerHeight - 31)
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
              系统设置: "settings",
            }[name] +
            ".png",
        ),
      });
    }
  }

  const commands = await page.evaluate(() => window.__commands);
  fs.writeFileSync(
    path.join(output, "report.json"),
    JSON.stringify({ measurements, errors, commands }, null, 2),
  );
  await browser.close();
  if (errors.length) throw new Error(errors.join("\n"));
  console.log(
    "UI review passed: " +
      measurements.length +
      " page/theme/viewport combinations; logs, order navigation and confirmation verified. Screenshots: " +
      output,
  );
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
