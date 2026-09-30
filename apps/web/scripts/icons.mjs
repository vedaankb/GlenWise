// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

// Renders public/icon.svg to the PNG sizes browsers and app stores expect. Run: pnpm --filter @gleanwise/web icons
import { Resvg } from "@resvg/resvg-js";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";

const svg = readFileSync(new URL("../public/icon.svg", import.meta.url), "utf8");
const out = new URL("../public/icons/", import.meta.url);
mkdirSync(out, { recursive: true });
const render = (svgText, size) => new Resvg(svgText, { fitTo: { mode: "width", value: size } }).render().asPng();

writeFileSync(new URL("icon-192.png", out), render(svg, 192));
writeFileSync(new URL("icon-512.png", out), render(svg, 512));
writeFileSync(new URL("apple-touch-icon.png", out), render(svg.replace('rx="112"', 'rx="0"'), 180));
// Maskable icons need the artwork inside the central 80% safe zone, on a full-bleed background.
const mask =
  svg
    .replace('rx="112"', 'rx="0"')
    .replace("</svg>", "")
    .replace(/<circle cx="232"[\s\S]*$/, "") +
  `<g transform="translate(51 51) scale(.8)"><circle cx="232" cy="232" r="104" fill="none" stroke="#fafaf8" stroke-width="40"/><path d="M312 312l88 88" stroke="#fafaf8" stroke-width="44" stroke-linecap="round"/><circle cx="232" cy="232" r="34" fill="#818cf8"/></g></svg>`;
writeFileSync(new URL("maskable-512.png", out), render(mask, 512));
console.log("icons written");
