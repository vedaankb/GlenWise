// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

import { defineConfig } from "vitest/config";
export default defineConfig({ test: { environment: "happy-dom", include: ["src/**/*.test.{ts,tsx}"] } });
