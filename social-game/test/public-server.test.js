import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import test from "node:test";

async function unusedPort() {
  const listener = net.createServer();
  listener.listen(0, "127.0.0.1");
  await once(listener, "listening");
  const { port } = listener.address();
  await new Promise((resolve, reject) => listener.close((error) => error ? reject(error) : resolve()));
  return port;
}

test("public game APIs preserve account, rewards, inventory and avatar state", async (context) => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "wyspy-public-test-"));
  const database = path.join(directory, "world.sqlite");
  const port = await unusedPort();
  const setupKey = "public-test-admin-key-32-characters-minimum";
  const child = spawn(process.execPath, ["server/index.js"], {
    cwd: path.resolve(import.meta.dirname, ".."),
    env: {
      ...process.env,
      NODE_ENV: "production",
      PORT: String(port),
      DATABASE_PATH: database,
      ADMIN_SETUP_KEY: setupKey,
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let output = "";
  child.stdout.setEncoding("utf8").on("data", (chunk) => { output += chunk; });
  child.stderr.setEncoding("utf8").on("data", (chunk) => { output += chunk; });
  context.after(async () => {
    child.kill("SIGTERM");
    await Promise.race([once(child, "exit"), new Promise((resolve) => setTimeout(resolve, 5_000))]);
    if (child.exitCode === null) child.kill("SIGKILL");
    fs.rmSync(directory, { recursive: true, force: true });
  });

  const base = `http://127.0.0.1:${port}`;
  let cookie = "";
  async function request(route, method = "GET", body, origin) {
    const response = await fetch(`${base}${route}`, {
      method,
      headers: {
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        ...(cookie ? { Cookie: cookie } : {}),
        ...(origin ? { Origin: origin } : {}),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    const sessionCookie = response.headers.get("set-cookie");
    if (sessionCookie) cookie = sessionCookie.split(";", 1)[0];
    return {
      response,
      data: response.status === 204 ? {} : await response.json(),
    };
  }

  let ready = false;
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try {
      if ((await fetch(`${base}/healthz`)).ok) {
        ready = true;
        break;
      }
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
  }
  assert.equal(ready, true, `Server failed to start. ${output}`);

  let result = await request("/api/auth/register", "POST", {
    username: "PublicAdmin",
    password: "A-long-public-test-password",
  });
  assert.equal(result.response.status, 201);
  assert.equal(result.data.user.coins, 300);
  result = await request("/api/auth/claim-admin", "POST", {
    setupKey,
    username: "PublicAdmin",
    password: "A-long-public-test-password",
  });
  assert.equal(result.response.status, 201);
  assert.equal(result.data.user.role, "admin");

  result = await request("/api/rewards/daily", "POST", {});
  assert.equal(result.response.status, 200);
  assert.equal(result.data.user.coins, 400);
  assert.equal((await request("/api/rewards/daily", "POST", {})).response.status, 409);

  result = await request("/api/shop/purchase", "POST", { catalogId: "leaf-chair" });
  assert.equal(result.response.status, 201);
  assert.equal(result.data.user.coins, 355);
  assert.equal(result.data.user.inventory[0].quantity, 1);
  result = await request("/api/furniture", "POST", {
    roomId: "sunny-square", catalogId: "leaf-chair", x: 0.5, y: 0.6,
  });
  assert.equal(result.response.status, 201);
  assert.equal(result.data.user.inventory[0].quantity, 0);
  result = await request("/api/admin/rooms/sunny-square/furniture", "DELETE");
  assert.equal(result.response.status, 200);
  assert.equal(result.data.cleared, 1);

  result = await request("/api/auth/profile", "PATCH", {
    avatarColor: "#e98773",
    skinTone: "#9c624a",
    hairColor: "#403d62",
    hairStyle: "curly",
  });
  assert.equal(result.response.status, 200);
  assert.equal(result.data.user.skinTone, "#9c624a");
  assert.equal(result.data.user.hairColor, "#403d62");
  assert.equal(result.data.user.hairStyle, "curly");
  assert.equal(
    (await request("/api/auth/profile", "PATCH", { hairStyle: "unknown" })).response.status,
    400,
  );
  assert.equal(
    (await request("/api/admin/broadcast", "POST", { message: "Nieautoryzowane" }, "https://not-the-game.example"))
      .response.status,
    403,
  );

  const page = await fetch(base);
  assert.equal(page.status, 200);
  assert.match(await page.text(), /Wyspy/);
});
