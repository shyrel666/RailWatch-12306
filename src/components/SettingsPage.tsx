import { Button, Switch } from "antd";
import { Activity, Download, LogIn, Trash2, XCircle } from "lucide-react";
import { useRailWatchStore } from "../store/useRailWatchStore";
import type { CommandRunner } from "./componentTypes";
import { SectionTitle } from "./FormPrimitives";

export function SettingsPage({
  busy,
  darkMode,
  runCommand,
  setDarkMode,
}: {
  busy: string | null;
  darkMode: boolean;
  runCommand: CommandRunner;
  setDarkMode: (value: boolean) => void;
}) {
  const runtime = useRailWatchStore((state) => state.runtime);
  const saveTheme = async (checked: boolean) => {
    setDarkMode(checked);
    await runCommand("savePreferences", { theme: checked ? "dark" : "light" });
  };
  return (
    <div className="settings-grid">
      <section className="content-band">
        <SectionTitle title="外观" />
        <div className="settings-row">
          <span>暗色模式</span>
          <Switch checked={darkMode} onChange={(checked) => void saveTheme(checked)} />
        </div>
      </section>
      <section className="content-band span-two">
        <SectionTitle title="数据" />
        <dl className="data-list">
          <dt>数据目录</dt>
          <dd>{runtime.data_dir}</dd>
          <dt>ChromeDriver</dt>
          <dd>{runtime.chromedriver_path}</dd>
          <dt>Chrome 版本</dt>
          <dd>{runtime.chrome_version}</dd>
        </dl>
      </section>
      <section className="content-band span-two">
        <SectionTitle title="控制" />
        <div className="control-grid">
          <Button icon={<Activity size={16} />} loading={busy === "checkEnvironment"} onClick={() => void runCommand("checkEnvironment")}>
            检查环境
          </Button>
          <Button
            icon={<Download size={16} />}
            loading={busy === "downloadChromeDriver"}
            onClick={() => void runCommand("downloadChromeDriver")}
            type="primary"
          >
            下载 ChromeDriver
          </Button>
          <Button icon={<LogIn size={16} />} loading={busy === "openLogin"} onClick={() => void runCommand("openLogin")}>
            打开登录
          </Button>
          <Button danger icon={<XCircle size={16} />} loading={busy === "closeBrowser"} onClick={() => void runCommand("closeBrowser")}>
            关闭浏览器
          </Button>
          <Button danger icon={<Trash2 size={16} />} loading={busy === "clearLocalData"} onClick={() => void runCommand("clearLocalData")}>
            清除数据
          </Button>
        </div>
      </section>
    </div>
  );
}
