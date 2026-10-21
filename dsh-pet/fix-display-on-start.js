// Startup fallback: if display was switched to none/web by tray/right-click menu,
// restore first pet to desktop so double-clicking start-marvis-pet.cmd always shows the pet.
import fs from "fs";
import os from "os";
import path from "path";

const file = path.join(os.homedir(), ".dsh", "dsh-pet", "main-config.jsonc");
if (!fs.existsSync(file)) process.exit(0);

let raw = fs.readFileSync(file, "utf8");
// strip UTF-8 BOM (may be left by PowerShell writes) before parse
if (raw.charCodeAt(0) === 0xfeff) raw = raw.slice(1);
// strip .jsonc comments before parse
raw = raw
  .replace(/\/\*[\s\S]*?\*\//g, "")
  .replace(/^\s*\/\/.*$/gm, "");

let cfg;
try {
  cfg = JSON.parse(raw);
} catch {
  process.exit(0); // parse failed, leave config untouched
}

const pets = Array.isArray(cfg.pets) ? cfg.pets : [];
if (!pets.length) process.exit(0);
// already has a desktop/both pet window, nothing to do
if (pets.some((p) => p && (p.display === "desktop" || p.display === "both"))) {
  process.exit(0);
}
// no pet on desktop -> restore first pet to desktop
const target = pets.find((p) => p && typeof p === "object");
if (!target) process.exit(0);
target.display = "desktop";
fs.writeFileSync(file, JSON.stringify(cfg, null, 2), "utf8");
process.exit(0);
