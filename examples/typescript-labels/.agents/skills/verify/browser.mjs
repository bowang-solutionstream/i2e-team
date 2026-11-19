import { readFile } from "node:fs/promises";
import { createServer } from "node:http";
import { once } from "node:events";
import { fileURLToPath } from "node:url";
import { isDeepStrictEqual } from "node:util";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const journeys = [
  { input: "  beta  \n猫   cat\n  beta\n\nAlpha ", expected: ["beta", "猫 cat", "beta", "", "Alpha"] },
  { input: " next\t label ", expected: ["next label"] },
];

function findControl(node, role, name) {
  if (node.role === role && node.name === name) return node.id;
  for (const child of node.children ?? []) {
    const id = findControl(child, role, name);
    if (id) return id;
  }
}

function readEvaluation(response) {
  const text = response.content.map(part => part.text ?? "").join("\n");
  const json = text.match(/```json\s*([\s\S]*?)\s*```/);
  if (!json) throw new Error("DevTools evaluation returned no JSON: " + text);
  return JSON.parse(json[1]);
}

export async function checkBrowser(root, assets) {
  const server = createServer((req, res) => {
    const asset = assets.get(req.url);
    if (!asset || req.method !== "GET") {
      res.writeHead(404).end();
      return;
    }
    res.writeHead(200, { "Content-Type": asset.type + "; charset=utf-8" }).end(asset.body);
  });

  const client = new Client({ name: "i2e-label-verifier", version: "1.0.0" });
  const mcpRoot = new URL("node_modules/chrome-devtools-mcp/", root);
  const pkg = JSON.parse(await readFile(new URL("package.json", mcpRoot), "utf8"));
  const bin = fileURLToPath(new URL(pkg.bin["chrome-devtools-mcp"], mcpRoot));
  const args = [bin, "--headless", "--isolated", "--experimental-structured-content",
    "--no-usage-statistics", "--no-performance-crux"];
  if (process.env.CHROME_EXECUTABLE) args.push("--executablePath", process.env.CHROME_EXECUTABLE);
  const calls = [];
  let pageId;
  async function call(name, params = {}) {
    const args = pageId === undefined ? params : { ...params, pageId };
    const reply = await client.callTool({ name, arguments: args }, undefined, { timeout: 30000 });
    if (reply.isError) throw new Error(name + ": " + JSON.stringify(reply.content));
    calls.push(name);
    return reply;
  }
  try {
    server.listen(0, "127.0.0.1");
    await once(server, "listening");
    const origin = "http://127.0.0.1:" + server.address().port;
    await client.connect(new StdioClientTransport({ command: process.execPath, args }));
    const pages = (await call("list_pages")).structuredContent.pages;
    const blank = pages.find(page => page.url === "about:blank");
    if (!Number.isInteger(blank?.id)) throw new Error("Missing isolated blank page");
    pageId = blank.id;
    await call("navigate_page", { type: "url", url: origin + "/" });
    const observed = [];
    const info = readEvaluation(await call("evaluate_script", {
      function: '() => ({ url: location.origin, browser: navigator.userAgent, initial: document.querySelectorAll("#results li").length })',
    }));
    if (info.url !== origin) throw new Error("Unexpected browser origin");
    for (const { input, expected } of journeys) {
      const snapshot = (await call("take_snapshot")).structuredContent.snapshot;
      const field = findControl(snapshot, "textbox", "Labels, one per line");
      const submit = findControl(snapshot, "button", "Normalize");
      if (!field || !submit) {
        observed.push({ input, expected, error: "Form control missing from accessibility tree" });
        break;
      }
      await call("fill", { uid: field, value: input });
      await call("click", { uid: submit });
      const actual = readEvaluation(await call("evaluate_script", {
        function: '() => Array.from(document.querySelectorAll("#results li"), item => item.checkVisibility() ? item.textContent : null)',
      }));
      observed.push({ input, expected, actual });
    }
    const consoleResult = await call("list_console_messages", { types: ["error", "warn"] });
    const messages = consoleResult.structuredContent?.consoleMessages ?? [];
    const network = (await call("list_network_requests")).structuredContent.networkRequests;
    const loaded = [...assets.keys()].every(path =>
      network.some(row => row.url === origin + path && String(row.status) === "200"));
    const passed = info.initial === 0 && loaded && messages.length === 0 &&
      observed.length === journeys.length && observed.every(row => isDeepStrictEqual(row.actual, row.expected));
    return { state: passed ? "PASS" : "FAIL", server: client.getServerVersion(),
      browser: info.browser, calls, initial: info.initial, journeys: observed, network, console: messages };
  } finally {
    try {
      await client.close();
    } finally {
      if (server.listening) {
        const closed = once(server, "close");
        server.close();
        server.closeAllConnections();
        await closed;
      }
    }
  }
}
