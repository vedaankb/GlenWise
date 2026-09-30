// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

import { createContext, useContext } from "react";

/** Every user-visible string in this package, so apps can translate it. */
export interface UiLabels {
  copy: string;
  copied: string;
  source: (n: number) => string;
  openSource: string;
  usedInAnswer: string;
  reading: string;
  failed: string;
  skipped: string;
  imageBlocked: string;
}

export const defaultLabels: UiLabels = {
  copy: "Copy",
  copied: "Copied",
  source: (n) => `Source ${n}`,
  openSource: "Open source",
  usedInAnswer: "Used in answer",
  reading: "Reading…",
  failed: "Couldn't open",
  skipped: "Skipped",
  imageBlocked: "Image not shown",
};

const LabelsCtx = createContext<UiLabels>(defaultLabels);
export const LabelsProvider = LabelsCtx.Provider;
export const useLabels = () => useContext(LabelsCtx);
