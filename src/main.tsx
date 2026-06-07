import "antd/dist/reset.css";
import React from "react";
import ReactDOM from "react-dom/client";
import { App as AntApp } from "antd";
import { RailWatchApp } from "./App";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <AntApp>
      <RailWatchApp />
    </AntApp>
  </React.StrictMode>,
);
