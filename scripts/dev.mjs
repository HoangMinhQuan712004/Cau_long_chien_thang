// Chạy môi trường local bằng một lệnh. Không dùng thư viện ngoài.
//   npm run dev     DB + Redis -> alembic upgrade -> uvicorn --reload + next dev song song
//   npm run dev:be  DB + Redis -> alembic upgrade -> uvicorn --reload
//   npm run dev:fe  next dev (BACKEND_URL theo API_PORT)
//   npm run seed    DB + Redis -> alembic upgrade -> python -m app.scripts.seed
//   npm run db      chỉ bật DB + Redis
// Cổng: API_PORT (mặc định 8010, vì 8000 hay bị Apache chiếm), WEB_PORT (mặc định 3000).
// Đặt trong biến môi trường hoặc file dev.env ở gốc repo (gitignore), ví dụ: API_PORT=8101
import { spawn, spawnSync, execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const isWin = process.platform === "win32";
const mode = process.argv[2] ?? "all";

function readEnvFile(file) {
  const out = {};
  if (!existsSync(file)) return out;
  for (const raw of readFileSync(file, "utf8").split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const i = line.indexOf("=");
    if (i > 0) out[line.slice(0, i).trim()] = line.slice(i + 1).trim().replace(/^["']|["']$/g, "");
  }
  return out;
}

const devEnv = readEnvFile(path.join(root, "dev.env"));
const cfg = (key, fallback) => process.env[key] ?? devEnv[key] ?? fallback;
const API_PORT = Number(cfg("API_PORT", "8010"));
const WEB_PORT = Number(cfg("WEB_PORT", "3000"));

const color = { be: "\x1b[36m", fe: "\x1b[35m", dev: "\x1b[33m" };
const reset = "\x1b[0m";
const say = (tag, msg) => console.log(`${color[tag] ?? ""}[${tag}]${reset} ${msg}`);
const fail = (msg) => {
  console.error(`\x1b[31m[dev] ${msg}${reset}`);
  process.exit(1);
};

function pump(tag, stream, target) {
  let buf = "";
  stream.on("data", (chunk) => {
    buf += chunk.toString();
    const lines = buf.split(/\r?\n/);
    buf = lines.pop();
    for (const l of lines) if (l.length) target.write(`${color[tag]}[${tag}]${reset} ${l}\n`);
  });
}

function portInUse(port) {
  return new Promise((resolve) => {
    const s = net.connect({ port, host: "127.0.0.1" });
    s.once("connect", () => (s.destroy(), resolve(true)));
    s.once("error", () => resolve(false));
    s.setTimeout(800, () => (s.destroy(), resolve(false)));
  });
}

function portOwner(port) {
  try {
    if (isWin) {
      const out = execFileSync("netstat", ["-ano", "-p", "TCP"], { encoding: "utf8" });
      const row = out.split(/\r?\n/).find((l) => l.includes("LISTENING") && new RegExp(`[:.]${port}\s`).test(l));
      const pid = row?.trim().split(/\s+/).pop();
      if (!pid) return "";
      const t = execFileSync("tasklist", ["/FI", `PID eq ${pid}`, "/FO", "CSV", "/NH"], { encoding: "utf8" });
      return `${t.split(",")[0]?.replace(/"/g, "")} (PID ${pid})`;
    }
    return execFileSync("lsof", ["-nP", `-iTCP:${port}`, "-sTCP:LISTEN"], { encoding: "utf8" }).split("\n")[1] ?? "";
  } catch {
    return "";
  }
}

async function ensurePortFree(port, name, envVar) {
  if (!(await portInUse(port))) return;
  const who = portOwner(port);
  fail(`Cổng ${port} (${name}) đang bị chiếm${who ? ` bởi ${who}` : ""}. Đổi cổng: ${envVar}=<cổng khác> npm run dev (hoặc ghi vào dev.env).`);
}

// Windows: npm là .cmd nên cần shell; truyền cả lệnh thành một chuỗi (truyền mảng args kèm shell bị Node cảnh báo)
function spawnArgs(cmd, args, opts) {
  return opts.shell ? [[cmd, ...args].join(" "), { ...opts }] : [cmd, args, opts];
}

function run(cmd, args, opts = {}) {
  const [c, ...rest] = spawnArgs(cmd, args, { stdio: "inherit", shell: false, ...opts });
  const r = spawnSync(c, ...rest);
  if (r.status !== 0) fail(`Lệnh thất bại: ${cmd} ${args.join(" ")}${r.error ? ` (${r.error.message})` : ""}`);
}

const venvBin = (name) => path.join(root, "backend", ".venv", isWin ? "Scripts" : "bin", isWin ? `${name}.exe` : name);

function checkBackendReady() {
  if (!existsSync(venvBin("alembic"))) {
    fail("Chưa có backend/.venv. Tạo: cd backend; python -m venv .venv; .venv\Scripts\pip install -e \".[dev]\"");
  }
  const envFile = path.join(root, "backend", ".env");
  if (!existsSync(envFile)) fail("Thiếu backend/.env (copy từ backend/.env.example).");
  const m = readFileSync(envFile, "utf8").match(/^ALLOWED_ORIGINS=(.*)$/m);
  const origin = `http://localhost:${WEB_PORT}`;
  if (m ? !m[1].includes(origin) : WEB_PORT !== 3000) {
    say("dev", `CẢNH BÁO: backend/.env chưa cho phép ${origin} trong ALLOWED_ORIGINS -> lệnh ghi (POST/PUT/PATCH/DELETE) sẽ bị 403. Thêm: ALLOWED_ORIGINS=["${origin}"]`);
  }
}

function startDb() {
  say("dev", "Bật DB + Redis (docker compose up -d --wait db redis)...");
  run("docker", ["compose", "up", "-d", "--wait", "db", "redis"], { cwd: root });
}

function migrate() {
  say("dev", "alembic upgrade head...");
  run(venvBin("alembic"), ["upgrade", "head"], { cwd: path.join(root, "backend") });
}

const children = [];
let stopping = false;
function stopAll(code = 0) {
  if (stopping) return;
  stopping = true;
  for (const c of children) {
    if (c.exitCode !== null) continue;
    if (isWin) spawnSync("taskkill", ["/pid", String(c.pid), "/T", "/F"], { stdio: "ignore" });
    else c.kill("SIGTERM");
  }
  setTimeout(() => process.exit(code), 300);
}
process.on("SIGINT", () => stopAll(0));
process.on("SIGTERM", () => stopAll(0));

function start(tag, cmd, args, opts) {
  const [bin, ...rest] = spawnArgs(cmd, args, { stdio: ["ignore", "pipe", "pipe"], shell: false, ...opts });
  const c = spawn(bin, ...rest);
  children.push(c);
  pump(tag, c.stdout, process.stdout);
  pump(tag, c.stderr, process.stderr);
  c.on("exit", (code) => {
    if (stopping) return;
    say(tag, `đã dừng (mã ${code}). Tắt phần còn lại.`);
    stopAll(code ?? 1);
  });
}

const startApi = () =>
  start("be", venvBin("uvicorn"), ["app.main:app", "--reload", "--port", String(API_PORT)], {
    cwd: path.join(root, "backend"),
  });

const startWeb = () =>
  start("fe", "npm", ["run", "dev", "--", "--port", String(WEB_PORT)], {
    shell: isWin,
    cwd: path.join(root, "frontend"),
    env: { ...process.env, BACKEND_URL: `http://localhost:${API_PORT}`, PORT: String(WEB_PORT) },
  });

switch (mode) {
  case "db":
    startDb();
    break;
  case "seed":
    checkBackendReady();
    startDb();
    migrate();
    run(venvBin("python"), ["-m", "app.scripts.seed"], { cwd: path.join(root, "backend") });
    break;
  case "be":
    checkBackendReady();
    await ensurePortFree(API_PORT, "API", "API_PORT");
    startDb();
    migrate();
    say("dev", `API: http://localhost:${API_PORT} (docs: /docs)`);
    startApi();
    break;
  case "fe":
    await ensurePortFree(WEB_PORT, "web", "WEB_PORT");
    say("dev", `Web: http://localhost:${WEB_PORT} -> API http://localhost:${API_PORT}`);
    startWeb();
    break;
  case "all":
    checkBackendReady();
    await ensurePortFree(API_PORT, "API", "API_PORT");
    await ensurePortFree(WEB_PORT, "web", "WEB_PORT");
    startDb();
    migrate();
    say("dev", `API: http://localhost:${API_PORT} · Web: http://localhost:${WEB_PORT} · Ctrl+C để tắt cả hai`);
    startApi();
    startWeb();
    break;
  default:
    fail(`Chế độ không hợp lệ: ${mode} (all | be | fe | seed | db)`);
}
