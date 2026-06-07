import "antd/dist/reset.css";
import React from "react";
import ReactDOM from "react-dom/client";
import { App as AntApp, ConfigProvider, theme } from "antd";
import { RailWatchApp } from "./App";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ConfigProvider
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: {
          colorPrimary: "#0f8f62",
          borderRadius: 6,
          fontFamily: '"Microsoft YaHei UI", "Noto Sans SC", "Segoe UI", sans-serif',
        },
      }}
    >
      <AntApp>
        <RailWatchApp />
      </AntApp>
    </ConfigProvider>
  </React.StrictMode>,
);
