import React from "react";
import ReactDOM from "react-dom/client";
import { ResearcherApp } from "./ResearcherApp";
import "../shared/styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ResearcherApp />
  </React.StrictMode>,
);
