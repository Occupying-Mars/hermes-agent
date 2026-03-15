import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { watch } from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const uiRoot = path.join(__dirname, "src-ui");
const host = "127.0.0.1";
const port = Number(process.env.AUTOCLYS_UI_PORT || "4310");

const contentTypes = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".ico": "image/x-icon",
};

const clients = new Set();

function resolveRequestPath(urlPath) {
  const pathname = urlPath === "/" ? "/index.html" : urlPath;
  const resolved = path.normalize(path.join(uiRoot, pathname));
  if (!resolved.startsWith(uiRoot)) {
    return null;
  }
  return resolved;
}

function injectReload(html) {
  const script = `
<script>
  (() => {
    const source = new EventSource('/__autoclys_reload');
    source.onmessage = () => window.location.reload();
  })();
</script>`;
  return html.includes("</body>") ? html.replace("</body>", `${script}\n</body>`) : `${html}\n${script}`;
}

const server = createServer(async (req, res) => {
  if (!req.url) {
    res.writeHead(400).end("bad request");
    return;
  }

  if (req.url === "/__autoclys_reload") {
    res.writeHead(200, {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    });
    res.write("\n");
    clients.add(res);
    req.on("close", () => clients.delete(res));
    return;
  }

  const filePath = resolveRequestPath(req.url.split("?")[0]);
  if (!filePath) {
    res.writeHead(403).end("forbidden");
    return;
  }

  try {
    const raw = await readFile(filePath);
    const ext = path.extname(filePath).toLowerCase();
    const type = contentTypes[ext] || "application/octet-stream";
    const body = ext === ".html" ? Buffer.from(injectReload(raw.toString("utf8"))) : raw;
    res.writeHead(200, { "Content-Type": type });
    res.end(body);
  } catch {
    res.writeHead(404).end("not found");
  }
});

const watcher = watch(uiRoot, { recursive: true }, () => {
  for (const client of clients) {
    client.write(`data: reload\n\n`);
  }
});

server.listen(port, host, () => {
  process.stdout.write(`autoclys ui dev server listening on http://${host}:${port}\n`);
});

function shutdown() {
  watcher.close();
  server.close(() => process.exit(0));
  for (const client of clients) {
    client.end();
  }
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
