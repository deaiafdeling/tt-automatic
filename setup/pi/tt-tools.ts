/**
 * TT bring-up tools for pi on the QuietBox.
 *
 * Registers model-callable tools:
 *  - github_search : GitHub API search via gh CLI (authed as deaiafdeling)
 *  - web_search    : DuckDuckGo HTML search (no API key, works from this box)
 *  - fetch_page    : GET a URL, strip tags, return readable text (truncated)
 *  - kanban        : read/append/tail /home/ttuser/tt-contrib/KANBAN.md
 *
 * registerTool takes ONE ToolDefinition object:
 *   { name, label, description, parameters (object schema), execute }
 * execute(toolCallId, params, signal, onUpdate, ctx) -> { content: [{type:"text",text}], details? }
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const UA = "Mozilla/5.0 (X11; Linux x86_64) pi-bringup/1.0";

function stripHtml(html: string): string {
  let s = html
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<!--[\s\S]*?-->/g, " ")
    .replace(/<[^>]+>/g, " ");
  return s
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&#\d+;/g, " ")
    .replace(/\s{2,}/g, " ")
    .trim();
}

async function run(cmd: string, args: string[], timeoutMs = 30000): Promise<string> {
  const { spawn } = await import("node:child_process");
  return await new Promise<string>((resolve) => {
    let out = "";
    let err = "";
    const p = spawn(cmd, args, { timeout: timeoutMs });
    p.stdout.on("data", (d: Buffer) => (out += d.toString()));
    p.stderr.on("data", (d: Buffer) => (err += d.toString()));
    const t = setTimeout(() => p.kill(), timeoutMs);
    p.on("close", (code) => {
      clearTimeout(t);
      const head = out.length > 12000 ? out.slice(0, 12000) + "\n[...truncated]" : out;
      resolve(
        (head ? head : "(no stdout)") +
          (err ? "\n[stderr] " + err.slice(0, 2000) : "") +
          `\n[exit ${code}]`,
      );
    });
    p.on("error", (e) => resolve("[spawn error] " + String(e)));
  });
}

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "github_search",
    label: "GitHub search",
    description:
      "Search GitHub via the gh CLI (authenticated). Kinds: issues, prs, code, repos. " +
      "Examples: {kind:'issues', query:'repo:tenstorrent/tt-metal moe dispatch'}, " +
      "{kind:'prs', query:'repo:tenstorrent/tt-metal is:open qsa'}, " +
      "{kind:'code', query:'qsa_score_merge repo:tenstorrent/tt-metal'}.",
    promptSnippet:
      "github_search: search GitHub issues/PRs/code/repos via gh (use before writing new ops — check upstream first).",
    parameters: {
      type: "object",
      properties: {
        kind: { type: "string", description: "issues|prs|code|repos" },
        query: { type: "string", description: "gh search query string" },
        limit: { type: "number", description: "max results (default 15)" },
      },
      required: ["kind", "query"],
    },
    execute: async (_toolCallId, params, _signal, _onUpdate, _ctx) => {
      const kind = String((params as any).kind);
      const limit = Number((params as any).limit) || 15;
      const fields = kind === "code"
        ? "path,repository,url"
        : "number,title,state,url";
      const args = ["search", kind];
      // gh CLI bug: 'repo:owner/name term' inside the query string gets shell-quoted
      // as repo:"owner/name term" -> invalid query. Extract repo: qualifiers and pass
      // them via the --repo flag instead.
      let query = String((params as any).query).replace(/(?:^|\s)repo:(\S+)/g, (_m, repo) => {
        args.push("--repo", repo);
        return " ";
      });
      args.push(query.trim(), "--limit", String(limit), "--json", fields);
      const out = await run("gh", args);
      return { content: [{ type: "text", text: out }], details: { out } };
    },
  });

  pi.registerTool({
    name: "web_search",
    label: "Web search",
    description:
      "Web search (DuckDuckGo HTML, no API key). Returns top results: title, URL, snippet. " +
      "Use for upstream docs, papers, forum threads, and checking if a solution exists before writing one.",
    promptSnippet:
      "web_search: DuckDuckGo search for docs/papers/threads — check existing solutions before writing new kernels.",
    parameters: {
      type: "object",
      properties: {
        query: { type: "string", description: "search query" },
        limit: { type: "number", description: "max results (default 10)" },
      },
      required: ["query"],
    },
    execute: async (_toolCallId, params, _signal, _onUpdate, _ctx) => {
      const query = String((params as any).query);
      const limit = Number((params as any).limit) || 10;
      const url = "https://duckduckgo.com/html/?q=" + encodeURIComponent(query);
      let results = "";
      try {
        const res = await fetch(url, { headers: { "User-Agent": UA }, signal: AbortSignal.timeout(20000) });
        const html = await res.text();
        const items: string[] = [];
        const re = /<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>([\s\S]*?)<\/a>[\s\S]*?(?:<a[^>]+class="result__snippet"[^>]*>([\s\S]*?)<\/a>)/g;
        let m: RegExpExecArray | null;
        while ((m = re.exec(html)) && items.length < limit) {
          items.push(`- ${stripHtml(m[2])}\n  ${m[1]}\n  ${stripHtml(m[3] || "")}`);
        }
        results = items.length ? items.join("\n") : "(no results parsed; query may have been blocked)";
      } catch (e) {
        results = "[web_search error] " + String(e);
      }
      return { content: [{ type: "text", text: results }], details: { results } };
    },
  });

  pi.registerTool({
    name: "fetch_page",
    label: "Fetch page",
    description:
      "GET a URL and return its readable text (HTML stripped, truncated to ~12k chars). " +
      "Use for reading docs, issue pages, PR pages, markdown sources (raw.githubusercontent.com).",
    promptSnippet: "fetch_page: read a URL's text (docs, issues, raw files).",
    parameters: {
      type: "object",
      properties: {
        url: { type: "string", description: "absolute http(s) URL" },
        max_chars: { type: "number", description: "max chars returned (default 12000)" },
      },
      required: ["url"],
    },
    execute: async (_toolCallId, params, _signal, _onUpdate, _ctx) => {
      const url = String((params as any).url);
      const max = Number((params as any).max_chars) || 12000;
      let text = "";
      try {
        const res = await fetch(url, { headers: { "User-Agent": UA }, signal: AbortSignal.timeout(30000) });
        const body = await res.text();
        text = stripHtml(body).slice(0, max);
        return {
          content: [{ type: "text", text: `[${res.status}] ${text}${body.length > max ? "\n[...truncated, " + body.length + " total chars]" : ""}` }],
          details: { text },
        };
      } catch (e) {
        return { content: [{ type: "text", text: "[fetch_page error] " + String(e) }], details: { text: String(e) } };
      }
    },
  });

  pi.registerTool({
    name: "kanban",
    label: "KANBAN",
    description:
      "Track bring-up work on /home/ttuser/tt-contrib/KANBAN.md (the pi setup lives in the P-series section). " +
      "Actions: read (whole file), append (add a line — status updates), tail (last N lines).",
    promptSnippet:
      "kanban: read/update tt-contrib/KANBAN.md — log completed work and open items there.",
    parameters: {
      type: "object",
      properties: {
        action: { type: "string", description: "read|append|tail" },
        line: { type: "string", description: "line to append (action=append)" },
        n: { type: "number", description: "lines for tail (default 30)" },
      },
      required: ["action"],
    },
    execute: async (_toolCallId, params, _signal, _onUpdate, _ctx) => {
      const path = "/home/ttuser/tt-contrib/KANBAN.md";
      const fs = await import("node:fs");
      const action = String((params as any).action);
      if (action === "append") {
        const line = String((params as any).line || "");
        fs.appendFileSync(path, (fs.existsSync(path) && !fs.readFileSync(path, "utf8").endsWith("\n") ? "\n" : "") + line + "\n");
        return { content: [{ type: "text", text: "appended: " + line }], details: { line } };
      }
      const body = fs.readFileSync(path, "utf8");
      const lines = body.split("\n");
      while (lines.length && lines[lines.length - 1] === "") lines.pop(); // drop trailing empties so tail n=1 is real content
      const out = action === "tail" ? lines.slice(-(Number((params as any).n) || 30)).join("\n") : body;
      const head = out.length > 12000 ? out.slice(-12000) + "\n[...truncated from head]" : out;
      return { content: [{ type: "text", text: head }], details: { out: head } };
    },
  });
}
