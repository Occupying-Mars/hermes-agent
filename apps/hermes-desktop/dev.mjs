import { spawn } from "node:child_process";
import process from "node:process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "../..");

const children = [];

function start(name, command, args, extraEnv = {}) {
  const child = spawn(command, args, {
    cwd: repoRoot,
    stdio: "inherit",
    env: { ...process.env, ...extraEnv },
  });
  children.push(child);
  child.on("exit", (code) => {
    if (code !== 0) {
      process.exitCode = code ?? 1;
      shutdown();
    }
  });
  return child;
}

function shutdown() {
  for (const child of children) {
    if (!child.killed) {
      child.kill("SIGTERM");
    }
  }
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);

start("ui", process.execPath, [path.join(__dirname, "dev-server.mjs")]);
setTimeout(() => {
  start("tauri", "cargo", ["run", "--manifest-path", "apps/hermes-desktop/src-tauri/Cargo.toml"]);
}, 500);
