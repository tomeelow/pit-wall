import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./app/App";
import "./app/styles.css";

const root = document.getElementById("root");
if (!root) throw new Error("#root element missing from index.html");

// Dark first: light only when the viewer asked for it.
try {
  document.documentElement.dataset.theme = localStorage.getItem("theme") === "light" ? "light" : "dark";
} catch {
  document.documentElement.dataset.theme = "dark";
}

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
