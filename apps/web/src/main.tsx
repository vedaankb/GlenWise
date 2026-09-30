// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

import "@fontsource-variable/fraunces/opsz.css";
import "@fontsource-variable/inter";
import "@fontsource-variable/newsreader/opsz.css";
import "@fontsource-variable/noto-naskh-arabic";
import "@fontsource-variable/noto-sans-arabic";
import * as Tooltip from "@radix-ui/react-tooltip";
import { StrictMode, Component, type ErrorInfo, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { Ambient } from "./components/Ambient";
import { I18nProvider } from "./i18n";
import { ActiveProvider } from "./state/active";
import { AppProvider } from "./state/app";
import "./styles.css";

class Boundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(error, info.componentStack);
  }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div role="alert" style={{ padding: "3rem 1.5rem", maxWidth: 480, margin: "0 auto", fontFamily: "system-ui" }}>
        <h1 style={{ fontSize: 22 }}>Something went wrong</h1>
        <p style={{ opacity: 0.7 }}>{this.state.error.message}</p>
        <button onClick={() => location.reload()} style={{ padding: "8px 16px", borderRadius: 10 }}>
          Reload
        </button>
      </div>
    );
  }
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Boundary>
      <I18nProvider>
        <AppProvider>
          <ActiveProvider>
            <Tooltip.Provider>
              <Ambient />
              <App />
            </Tooltip.Provider>
          </ActiveProvider>
        </AppProvider>
      </I18nProvider>
    </Boundary>
  </StrictMode>,
);

if ("serviceWorker" in navigator && import.meta.env.PROD) {
  addEventListener("load", () => void navigator.serviceWorker.register("/sw.js").catch(() => undefined));
}
