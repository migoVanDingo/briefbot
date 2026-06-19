import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { themeStyleSheet, initialTheme, applyTheme } from "./theme";
import "./styles/index.css";

// Inject theme variables (single source) before first paint, then apply the
// saved/preferred theme.
const style = document.createElement("style");
style.id = "theme-vars";
style.textContent = themeStyleSheet();
document.head.appendChild(style);
applyTheme(initialTheme());

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
