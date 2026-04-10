import React from "react";
import ReactDOM from "react-dom/client";
import { AnalyzerApp } from "./AnalyzerApp";
import "../shared/styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <AnalyzerApp />
  </React.StrictMode>,
);
