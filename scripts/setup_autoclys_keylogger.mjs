import { spawnSync } from "node:child_process";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "..");
const keyloggerRoot = path.join(repoRoot, "autoclys_keylogger");

if (process.platform !== "darwin") {
  process.stdout.write("autoclys keylogger setup skipped: desktop observation currently targets macos.\n");
  process.exit(0);
}

const result = spawnSync("npm", ["install"], {
  cwd: keyloggerRoot,
  stdio: "inherit",
  env: process.env,
});

if (result.status !== 0) {
  process.stderr.write(
    "autoclys keylogger setup failed. observation will stay unavailable until `npm --prefix autoclys_keylogger install` succeeds.\n"
  );
}
