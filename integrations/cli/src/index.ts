#!/usr/bin/env node
// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Ved Buddaraju

/**
 * gleanwise — ask the local GleanWise server from a terminal.
 * Answer text goes to stdout (pipe-friendly); progress and diagnostics go to stderr.
 */
import { writeFile } from "node:fs/promises";
import {
  createClient,
  GleanWiseError,
  describePhase,
  reduce,
  startState,
  type Focus,
  type Mode,
} from "@gleanwise/client";

const USAGE = `gleanwise — cited answers from your own machine

Usage:
  gleanwise ask <question…> [--mode quick|pro|deep] [--focus general|academic|news|social] [--thread <id>] [--json] [--no-status]
  gleanwise search <query…> [--focus …] [--json]
  gleanwise threads [--json]
  gleanwise export <thread_id> [--format md|pdf] [--out <file>]
  gleanwise cancel <query_id>
  gleanwise health

Environment:
  GLEANWISE_API_URL    server address (default http://127.0.0.1:8787)
  GLEANWISE_API_TOKEN  bearer token, if the server requires one
`;

const client = createClient({
  baseUrl: process.env.GLEANWISE_API_URL || "http://127.0.0.1:8787",
  token: process.env.GLEANWISE_API_TOKEN,
});

class UsageError extends Error {}

function parseArgs(argv: string[], valueFlags: string[], boolFlags: string[]) {
  const flags: Record<string, string | boolean> = {};
  const rest: string[] = [];
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith("--")) {
      const name = a.slice(2);
      if (valueFlags.includes(name)) {
        const v = argv[++i];
        if (v === undefined) throw new UsageError(`--${name} needs a value`);
        flags[name] = v;
      } else if (boolFlags.includes(name)) flags[name] = true;
      else throw new UsageError(`Unknown option --${name}`);
    } else rest.push(a);
  }
  return { flags, text: rest.join(" ").trim(), rest };
}

function oneOf<T extends string>(name: string, v: unknown, allowed: readonly T[], fallback: T): T {
  if (v === undefined) return fallback;
  if (!allowed.includes(v as T)) throw new UsageError(`--${name} must be one of: ${allowed.join(", ")}`);
  return v as T;
}

async function ask(argv: string[]) {
  const { flags, text } = parseArgs(argv, ["mode", "focus", "thread"], ["json", "no-status"]);
  if (!text) throw new UsageError('Ask something, e.g. gleanwise ask "how do transformers work?"');
  const mode: Mode = oneOf("mode", flags.mode, ["quick", "pro", "deep"], "quick");
  const focus: Focus = oneOf("focus", flags.focus, ["general", "academic", "news", "social"], "general");
  const showStatus = !flags["no-status"] && process.stderr.isTTY;
  const controller = new AbortController();
  process.once("SIGINT", () => controller.abort());

  const handle = await client.query(
    { query: text, mode, focus, thread_id: flags.thread as string | undefined },
    { signal: controller.signal },
  );
  process.once("SIGINT", () => void handle.cancel().catch(() => undefined));

  let state = startState(handle.queryId, handle.threadId);
  let printed = 0;
  let lastStatus = "";
  const status = (s: string) => {
    if (showStatus && s !== lastStatus) {
      process.stderr.write(`\r\x1b[2K\x1b[2m${s}\x1b[0m`);
      lastStatus = s;
    }
  };
  const clearStatus = () => showStatus && process.stderr.write("\r\x1b[2K");

  for await (const ev of handle.events()) {
    state = reduce(state, ev);
    if (ev.event === "error") throw new GleanWiseError(ev.data);
    if (flags.json) continue;
    if (state.phase === "writing" && !state.draft) {
      // Stream only the real answer; a quick draft is replaced, so printing it would be misleading.
      clearStatus();
      process.stdout.write(state.answer.slice(printed));
      printed = state.answer.length;
    } else {
      if (printed && state.answer.length < printed) printed = 0; // answer was reset by an upgrade
      status(describePhase(state));
    }
  }
  clearStatus();

  if (flags.json) {
    process.stdout.write(
      JSON.stringify(
        {
          query_id: state.queryId,
          thread_id: state.threadId,
          answer: state.answer,
          citations: state.citations,
          sources: state.sources,
          follow_ups: state.followUps,
          usage: state.usage,
        },
        null,
        2,
      ) + "\n",
    );
    return;
  }
  if (state.answer.length > printed) process.stdout.write(state.answer.slice(printed));
  process.stdout.write("\n");
  const cited = state.citations.length ? state.citations : [];
  if (cited.length) {
    process.stdout.write("\nSources\n");
    for (const c of cited) process.stdout.write(`  [${c.number}] ${c.title || c.url}\n      ${c.url}\n`);
  }
  if (state.warnings.length) for (const w of state.warnings) process.stderr.write(`note: ${w.message}\n`);
  if (state.phase === "cancelled") process.stderr.write("(cancelled)\n");
  process.stderr.write(`thread ${state.threadId}\n`);
}

async function main() {
  const [cmd, ...rest] = process.argv.slice(2);
  switch (cmd) {
    case undefined:
    case "-h":
    case "--help":
    case "help":
      process.stdout.write(USAGE);
      return;
    case "ask":
      return ask(rest);
    case "search": {
      const { flags, text } = parseArgs(rest, ["focus"], ["json"]);
      if (!text) throw new UsageError("Search for what?");
      const focus = oneOf("focus", flags.focus, ["general", "academic", "news", "social"], "general");
      const res = await client.search(text, { focus });
      if (flags.json) return void process.stdout.write(JSON.stringify(res, null, 2) + "\n");
      for (const s of res.results) process.stdout.write(`${s.title}\n  ${s.url}\n  ${s.snippet ?? ""}\n\n`);
      return;
    }
    case "threads": {
      const { flags } = parseArgs(rest, [], ["json"]);
      const list = await client.listThreads({ limit: 50 });
      if (flags.json) return void process.stdout.write(JSON.stringify(list, null, 2) + "\n");
      for (const t of list) process.stdout.write(`${t.id}  ${t.pinned ? "★ " : ""}${t.title}\n`);
      return;
    }
    case "export": {
      const { flags, rest: ids } = parseArgs(rest, ["format", "out"], []);
      if (!ids[0]) throw new UsageError("Which thread? See `gleanwise threads`.");
      const format = oneOf("format", flags.format, ["md", "pdf"], "md");
      const blob = await client.exportThread(ids[0], format);
      if (flags.out) {
        await writeFile(String(flags.out), Buffer.from(await blob.arrayBuffer()));
        process.stderr.write(`wrote ${flags.out}\n`);
      } else if (format === "pdf") throw new UsageError("PDF is binary — pass --out <file>.");
      else process.stdout.write(await blob.text());
      return;
    }
    case "cancel":
      if (!rest[0]) throw new UsageError("Which query id?");
      await client.cancel(rest[0]);
      process.stdout.write("cancelled\n");
      return;
    case "health": {
      const h = await client.diagnostics();
      process.stdout.write(JSON.stringify(h, null, 2) + "\n");
      return;
    }
    default:
      throw new UsageError(`Unknown command "${cmd}"`);
  }
}

main().catch((e: unknown) => {
  if (e instanceof UsageError) {
    process.stderr.write(`${e.message}\n\n${USAGE}`);
    process.exit(2);
  }
  if ((e as Error)?.name === "AbortError") process.exit(130);
  if (e instanceof GleanWiseError) {
    process.stderr.write(`error: ${e.message}\n${e.hint ? `  ${e.hint}\n` : ""}`);
    process.exit(1);
  }
  process.stderr.write(`error: ${e instanceof Error ? e.message : String(e)}\n`);
  process.exit(1);
});
