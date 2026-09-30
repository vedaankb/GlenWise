// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

let n = 0;
/** A unique-enough client id (works on plain-http LAN addresses, where crypto.randomUUID is unavailable). */
export const uid = () => `t${Date.now().toString(36)}${(n++).toString(36)}${Math.random().toString(36).slice(2, 6)}`;
