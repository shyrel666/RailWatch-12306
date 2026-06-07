import "antd/dist/reset.css";
import React from "react";
import ReactDOM from "react-dom/client";
import { RailWatchApp } from "./App";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <RailWatchApp />
  </React.StrictMode>,
);
