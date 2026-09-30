// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

const target = process.env.GLEANWISE_API_URL ?? "http://127.0.0.1:8787";
const api = [
  "/query",
  "/stream",
  "/queries",
  "/threads",
  "/settings",
  "/setup",
  "/health",
  "/livez",
  "/readyz",
  "/diagnostics",
  "/proxy",
  "/data",
  "/feedback",
  "/search",
  "/fetch",
  "/retrieve",
  "/opensearch.xml",
];

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
      // Use the primitives from source so the Markdown renderer can be code-split out of the first load.
      "@ui": fileURLToPath(new URL("../../packages/ui/src", import.meta.url)),
    },
  },
  build: { target: "es2022", sourcemap: true, chunkSizeWarningLimit: 900 },
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      api.map((p) => [
        p,
        {
          target,
          changeOrigin: true,
          // The core refuses cross-origin writes; present the dev server as the API's own origin.
          configure: (proxy: { on(ev: string, cb: (req: { setHeader(k: string, v: string): void }) => void): void }) =>
            proxy.on("proxyReq", (req) => req.setHeader("origin", target)),
        },
      ]),
    ),
  },
});
