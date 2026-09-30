// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

/** Minimal, spec-compliant Server-Sent Events parser over a fetch() body. */

export interface SseMessage {
  id?: string;
  event: string;
  data: string;
  retry?: number;
}

/**
 * Yields one message per blank-line-terminated block. Handles LF, CRLF and CR line endings,
 * multi-line `data:`, comments (`:`), a UTF-8 BOM, and chunk boundaries anywhere (even mid-character).
 */
export async function* parseSse(body: ReadableStream<Uint8Array>): AsyncGenerator<SseMessage> {
  const reader = body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let first = true;
  let id: string | undefined;
  let event = "";
  let data: string[] = [];
  let retry: number | undefined;

  const dispatch = (): SseMessage | null => {
    if (data.length === 0 && !event) {
      event = "";
      retry = undefined;
      return null;
    }
    const msg: SseMessage = { id, event: event || "message", data: data.join("\n"), retry };
    event = "";
    data = [];
    retry = undefined;
    return msg;
  };

  const handleLine = (line: string): SseMessage | null => {
    if (line === "") return dispatch();
    if (line.startsWith(":")) return null;
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    switch (field) {
      case "event":
        event = value;
        break;
      case "data":
        data.push(value);
        break;
      case "id":
        if (!value.includes("\0")) id = value;
        break;
      case "retry":
        if (/^\d+$/.test(value)) retry = Number(value);
        break;
    }
    return null;
  };

  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      if (first) {
        buffer = buffer.replace(/^\uFEFF/, "");
        first = false;
      }
      let start = 0;
      for (let i = 0; i < buffer.length; i++) {
        const ch = buffer[i];
        if (ch !== "\n" && ch !== "\r") continue;
        if (ch === "\r" && i === buffer.length - 1) break; // might be CRLF split across chunks
        const msg = handleLine(buffer.slice(start, i));
        if (ch === "\r" && buffer[i + 1] === "\n") i++;
        start = i + 1;
        if (msg) {
          buffer = buffer.slice(start);
          start = 0;
          i = -1;
          yield msg;
        }
      }
      buffer = buffer.slice(start);
    }
    buffer += decoder.decode();
    if (buffer) {
      const msg = handleLine(buffer.replace(/[\r\n]+$/, ""));
      if (msg) yield msg;
    }
    // An unterminated final block is discarded, as the spec requires.
  } finally {
    reader.releaseLock();
  }
}
