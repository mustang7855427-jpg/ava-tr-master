import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import bcrypt from "bcryptjs";
import express from "express";
import helmet from "helmet";
import { Server } from "socket.io";
import { createAuthRouter, getUserForToken, readSessionToken, requireAdmin, requireUser } from "./auth.js";
import { db, publicUser, statements } from "./db.js";
import { AVATAR_COLORS, FURNITURE, HAIR_COLORS, HAIR_STYLES, ROOMS, SKIN_TONES } from "./rooms.js";

const directory = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(directory, "..");
const port = Number(process.env.PORT) || 3000;
const app = express();
const server = http.createServer(app);
const isDevelopment = process.env.NODE_ENV !== "production";
const io = new Server(server, {
  serveClient: false,
  cors: {
    origin: isDevelopment
      ? ["http://localhost:5173", "http://127.0.0.1:5173"]
      : false,
  },
  maxHttpBufferSize: 16_384,
  pingInterval: 25_000,
  pingTimeout: 20_000,
});
const roomPlayers = new Map(ROOMS.map((room) => [room.id, new Map()]));
const chatRate = new Map();
const positionRate = new Map();
const roomById = new Map(ROOMS.map((room) => [room.id, room]));
const furnitureById = new Map(FURNITURE.map((item) => [item.id, item]));

app.disable("x-powered-by");
app.set("trust proxy", process.env.TRUST_PROXY_HOPS === "1" ? 1 : false);
app.use(helmet({
  contentSecurityPolicy: {
    directives: {
      defaultSrc: ["'self'"],
      scriptSrc: ["'self'"],
      styleSrc: ["'self'", "'unsafe-inline'"],
      imgSrc: ["'self'", "data:"],
      connectSrc: ["'self'", "ws:", "wss:"],
      objectSrc: ["'none'"],
      baseUri: ["'self'"],
      frameAncestors: ["'none'"],
    },
  },
}));
app.use(express.json({ limit: "16kb" }));

app.use((request, response, next) => {
  if (request.method === "GET" || request.method === "HEAD"
      || !request.headers.origin) return next();
  const origin = request.headers.origin;
  const host = request.headers.host;
  let originHost;
  try {
    originHost = new URL(origin).host;
  } catch {
    return response.status(403).json({ error: "Niedozwolone źródło żądania." });
  }
  const isViteOrigin = isDevelopment
    && ["http://localhost:5173", "http://127.0.0.1:5173"].includes(origin);
  if (!host || (originHost !== host && !isViteOrigin)) {
    return response.status(403).json({ error: "Niedozwolone źródło żądania." });
  }
  return next();
});

app.get("/healthz", (_request, response) => response.json({ status: "ok" }));
app.use("/api/auth", createAuthRouter());

app.get("/api/rooms", requireUser, (_request, response) => {
  response.json({
    rooms: ROOMS.map((room) => ({
      ...room,
      online: roomPlayers.get(room.id)?.size || 0,
    })),
  });
});

app.get("/api/catalog", requireUser, (_request, response) => {
  response.json({ furniture: FURNITURE });
});

app.post("/api/shop/purchase", requireUser, (request, response) => {
  const item = furnitureById.get(request.body?.catalogId);
  if (!item) return response.status(400).json({ error: "Nie znaleziono takiego mebla." });
  const purchase = db.transaction(() => {
    const user = statements.userById.get(request.user.id);
    if (user.coins < item.price) return { error: "Masz za mało monet na ten mebel." };
    statements.adjustCoins.run(-item.price, user.id);
    const quantity = statements.inventoryCount.get(user.id, item.id)?.quantity || 0;
    statements.setInventory.run(user.id, item.id, quantity + 1);
    return { user: statements.userById.get(user.id) };
  });
  const result = purchase();
  if (result.error) return response.status(409).json({ error: result.error });
  return response.status(201).json({ user: publicUser(result.user) });
});

app.post("/api/rewards/daily", requireUser, (request, response) => {
  const claim = db.transaction(() => {
    const user = statements.userById.get(request.user.id);
    if (user.daily_reward_at > Date.now() - 24 * 60 * 60 * 1000) {
      return { error: "Dzienną nagrodę możesz odebrać raz na 24 godziny." };
    }
    statements.claimDailyReward.run(Date.now(), user.id);
    return { user: statements.userById.get(user.id) };
  });
  const result = claim();
  if (result.error) return response.status(409).json({ error: result.error });
  return response.json({ user: publicUser(result.user) });
});

app.get("/api/rooms/:roomId/furniture", requireUser, (request, response) => {
  if (!roomById.has(request.params.roomId)) {
    return response.status(404).json({ error: "Nie znaleziono tego pokoju." });
  }
  const furniture = statements.furnitureInRoom.all(request.params.roomId);
  return response.json({ furniture });
});

app.post("/api/furniture", requireUser, (request, response) => {
  const { roomId, catalogId, x, y } = request.body || {};
  if (!roomById.has(roomId) || !furnitureById.has(catalogId)
      || !Number.isFinite(x) || !Number.isFinite(y)
      || x < 0 || x > 1 || y < 0 || y > 1) {
    return response.status(400).json({ error: "Nieprawidłowe miejsce lub mebel." });
  }
  if (statements.furnitureCountInRoom.get(roomId).count >= 200) {
    return response.status(409).json({ error: "W tym pokoju nie ma już miejsca na kolejne meble." });
  }
  const place = db.transaction(() => {
    const quantity = statements.inventoryCount.get(request.user.id, catalogId)?.quantity || 0;
    if (quantity < 1) return { error: "Nie masz tego mebla w plecaku. Kup go najpierw w sklepie." };
    const result = statements.addFurniture.run(
      roomId, catalogId, x, y, request.user.id, Date.now(),
    );
    statements.setInventory.run(request.user.id, catalogId, quantity - 1);
    return {
      id: Number(result.lastInsertRowid),
      user: statements.userById.get(request.user.id),
    };
  });
  const result = place();
  if (result.error) return response.status(409).json({ error: result.error });
  const item = {
    id: result.id,
    room_id: roomId,
    catalog_id: catalogId,
    x,
    y,
    placed_by: request.user.id,
  };
  io.to(roomId).emit("furniture:added", item);
  return response.status(201).json({ furniture: item, user: publicUser(result.user) });
});

app.delete("/api/furniture/:id", requireUser, (request, response) => {
  const furnitureId = Number(request.params.id);
  if (!Number.isSafeInteger(furnitureId)) {
    return response.status(400).json({ error: "Nieprawidłowy identyfikator mebla." });
  }
  const item = statements.furnitureById.get(furnitureId);
  if (!item) return response.status(404).json({ error: "Nie znaleziono mebla." });
  if (item.placed_by !== request.user.id && request.user.role !== "admin") {
    return response.status(403).json({ error: "Możesz usunąć tylko swój mebel." });
  }
  const remove = db.transaction(() => {
    statements.removeFurniture.run(furnitureId);
    const quantity = statements.inventoryCount.get(item.placed_by, item.catalog_id)?.quantity || 0;
    statements.setInventory.run(item.placed_by, item.catalog_id, quantity + 1);
    return item.placed_by === request.user.id
      ? statements.userById.get(request.user.id) : null;
  });
  const updatedUser = remove();
  io.to(`user:${item.placed_by}`).emit("inventory:refresh");
  io.to(item.room_id).emit("furniture:removed", { id: furnitureId });
  return response.json({
    ok: true,
    ...(updatedUser ? { user: publicUser(updatedUser) } : {}),
  });
});

app.get("/api/admin/overview", requireUser, requireAdmin, (_request, response) => {
  response.json({
    online: [...roomPlayers.values()].reduce((total, room) => total + room.size, 0),
    rooms: ROOMS.map((room) => ({ ...room, online: roomPlayers.get(room.id).size })),
    users: statements.allUsers.all().map((user) => {
      const { password_hash: _passwordHash, ...safeUser } = user;
      return safeUser;
    }),
  });
});

const adminAction = [requireUser, requireAdmin];
app.patch("/api/admin/users/:userId/role", ...adminAction, (request, response) => {
  const userId = Number(request.params.userId);
  const { role } = request.body || {};
  if (!Number.isSafeInteger(userId) || !["player", "admin"].includes(role)) {
    return response.status(400).json({ error: "Nieprawidłowa ranga lub konto." });
  }
  if (userId === request.user.id && role !== "admin") {
    return response.status(400).json({ error: "Nie możesz odebrać sobie ostatniej aktywnej sesji administratora." });
  }
  const user = statements.userById.get(userId);
  if (!user) return response.status(404).json({ error: "Nie znaleziono gracza." });
  statements.updateRole.run(role, userId);
  io.to(`user:${userId}`).emit("account:refresh");
  return response.json({ ok: true });
});

app.post("/api/admin/users/:userId/coins", ...adminAction, (request, response) => {
  const userId = Number(request.params.userId);
  const amount = request.body?.amount;
  if (!Number.isSafeInteger(userId) || !Number.isSafeInteger(amount)
      || amount < 1 || amount > 100_000) {
    return response.status(400).json({ error: "Kwota musi wynosić od 1 do 100 000 monet." });
  }
  const user = statements.userById.get(userId);
  if (!user) return response.status(404).json({ error: "Nie znaleziono gracza." });
  statements.adjustCoins.run(amount, userId);
  io.to(`user:${userId}`).emit("inventory:refresh");
  return response.json({ ok: true, coins: user.coins + amount });
});

app.post("/api/admin/users/:userId/moderation", ...adminAction, (request, response) => {
  const userId = Number(request.params.userId);
  const { action, minutes } = request.body || {};
  if (!Number.isSafeInteger(userId) || userId === request.user.id
      || !["mute", "ban", "unmute", "unban"].includes(action)) {
    return response.status(400).json({ error: "Nieprawidłowa akcja moderacji." });
  }
  const user = statements.userById.get(userId);
  if (!user) return response.status(404).json({ error: "Nie znaleziono gracza." });
  const duration = Math.min(10_080, Math.max(1, Number(minutes) || 10)) * 60_000;
  const mutedUntil = action === "mute" ? Date.now() + duration
    : action === "unmute" ? 0 : user.muted_until;
  const bannedUntil = action === "ban" ? Date.now() + duration
    : action === "unban" ? 0 : user.banned_until;
  statements.updateModeration.run(mutedUntil, bannedUntil, userId);
  if (action === "ban") io.to(`user:${userId}`).emit("account:banned");
  else io.to(`user:${userId}`).emit("account:refresh");
  return response.json({ ok: true, mutedUntil, bannedUntil });
});

app.post("/api/admin/users/:userId/password", ...adminAction, (request, response) => {
  const userId = Number(request.params.userId);
  const { password } = request.body || {};
  if (!Number.isSafeInteger(userId) || typeof password !== "string"
      || password.length < 10 || password.length > 128) {
    return response.status(400).json({ error: "Nowe hasło musi mieć od 10 do 128 znaków." });
  }
  if (!statements.userById.get(userId)) {
    return response.status(404).json({ error: "Nie znaleziono gracza." });
  }
  statements.updatePassword.run(bcrypt.hashSync(password, 12), userId);
  db.prepare("DELETE FROM sessions WHERE user_id = ?").run(userId);
  io.to(`user:${userId}`).emit("account:refresh");
  return response.json({ ok: true });
});

app.post("/api/admin/broadcast", ...adminAction, (request, response) => {
  const message = typeof request.body?.message === "string"
    ? request.body.message.trim() : "";
  if (!message || message.length > 300) {
    return response.status(400).json({ error: "Ogłoszenie musi mieć 1–300 znaków." });
  }
  io.emit("chat:message", {
    system: true,
    username: "OGŁOSZENIE",
    text: message,
    timestamp: Date.now(),
  });
  return response.json({ ok: true });
});

app.delete("/api/admin/rooms/:roomId/furniture", ...adminAction, (request, response) => {
  const roomId = request.params.roomId;
  if (!roomById.has(roomId)) {
    return response.status(404).json({ error: "Nie znaleziono pokoju." });
  }
  const clearRoom = db.transaction(() => {
    const items = statements.furnitureInRoom.all(roomId);
    const refunds = new Map();
    for (const item of items) {
      const key = `${item.placed_by}:${item.catalog_id}`;
      refunds.set(key, (refunds.get(key) || 0) + 1);
    }
    for (const [key, quantity] of refunds) {
      const separator = key.indexOf(":");
      const userId = Number(key.slice(0, separator));
      const catalogId = key.slice(separator + 1);
      const currentQuantity = statements.inventoryCount.get(userId, catalogId)?.quantity || 0;
      statements.setInventory.run(userId, catalogId, currentQuantity + quantity);
    }
    statements.clearRoomFurniture.run(roomId);
    return items.length;
  });
  const cleared = clearRoom();
  io.emit("inventory:refresh");
  io.to(roomId).emit("furniture:cleared");
  return response.json({ ok: true, cleared });
});

io.use((socket, next) => {
  const token = readSessionToken({ headers: { cookie: socket.request.headers.cookie } });
  const user = getUserForToken(token);
  if (!user) return next(new Error("Zaloguj się ponownie."));
  socket.data.user = publicUser(user);
  return next();
});

function canAct(socket, bucket, limit, interval) {
  const now = Date.now();
  const key = `${socket.data.user.id}:${bucket}`;
  const previous = bucket === "chat" ? chatRate.get(key) : positionRate.get(key);
  if (previous && now - previous < interval) return false;
  const map = bucket === "chat" ? chatRate : positionRate;
  map.set(key, now);
  if (map.size > 2_000) {
    for (const [itemKey, itemTime] of map) {
      if (now - itemTime > interval * 2) map.delete(itemKey);
    }
  }
  return true;
}

io.on("connection", (socket) => {
  const user = socket.data.user;
  socket.join(`user:${user.id}`);
  socket.data.roomId = null;
  socket.data.position = { x: 0.5, y: 0.68 };

  socket.on("room:join", (roomId, callback) => {
    const acknowledge = typeof callback === "function" ? callback : () => {};
    if (typeof roomId !== "string" || !roomById.has(roomId)) {
      return acknowledge({ error: "Nieznany pokój." });
    }
    const nextRoom = roomPlayers.get(roomId);
    if (!nextRoom.has(socket.id) && nextRoom.size >= 32) {
      return acknowledge({ error: "Ten pokój jest pełny." });
    }
    if (socket.data.roomId) {
      const previousRoom = roomPlayers.get(socket.data.roomId);
      previousRoom?.delete(socket.id);
      socket.to(socket.data.roomId).emit("player:left", { id: user.id });
      socket.leave(socket.data.roomId);
      io.to(socket.data.roomId).emit("room:count", previousRoom?.size || 0);
    }
    socket.data.roomId = roomId;
    nextRoom.set(socket.id, {
      id: user.id,
      username: user.username,
      avatarColor: socket.data.user.avatarColor,
      skinTone: socket.data.user.skinTone,
      hairColor: socket.data.user.hairColor,
      hairStyle: socket.data.user.hairStyle,
      ...socket.data.position,
    });
    socket.join(roomId);
    const players = [...nextRoom.values()];
    acknowledge({
      room: roomById.get(roomId),
      players,
      furniture: statements.furnitureInRoom.all(roomId),
      count: nextRoom.size,
    });
    socket.to(roomId).emit("player:joined", {
      id: user.id,
      username: user.username,
      avatarColor: socket.data.user.avatarColor,
      skinTone: socket.data.user.skinTone,
      hairColor: socket.data.user.hairColor,
      hairStyle: socket.data.user.hairStyle,
      ...socket.data.position,
    });
    io.to(roomId).emit("room:count", nextRoom.size);
  });

  socket.on("player:move", (position) => {
    if (!socket.data.roomId || !canAct(socket, "position", 1, 45)
        || !position || !Number.isFinite(position.x) || !Number.isFinite(position.y)) return;
    const x = Math.min(0.94, Math.max(0.06, position.x));
    const y = Math.min(0.88, Math.max(0.3, position.y));
    socket.data.position = { x, y };
    const currentPlayer = roomPlayers.get(socket.data.roomId)?.get(socket.id);
    if (!currentPlayer) return;
    roomPlayers.get(socket.data.roomId).set(socket.id, {
      ...currentPlayer,
      id: user.id,
      username: user.username,
      avatarColor: socket.data.user.avatarColor,
      skinTone: socket.data.user.skinTone,
      hairColor: socket.data.user.hairColor,
      hairStyle: socket.data.user.hairStyle,
      x,
      y,
    });
    socket.to(socket.data.roomId).volatile.emit("player:moved", {
      id: user.id,
      x,
      y,
      avatarColor: socket.data.user.avatarColor,
      skinTone: socket.data.user.skinTone,
      hairColor: socket.data.user.hairColor,
      hairStyle: socket.data.user.hairStyle,
    });
  });

  socket.on("player:profile", () => {
    const profile = statements.userById.get(user.id);
    socket.data.user.avatarColor = profile.avatar_color;
    socket.data.user.skinTone = profile.skin_tone;
    socket.data.user.hairColor = profile.hair_color;
    socket.data.user.hairStyle = profile.hair_style;
    if (!AVATAR_COLORS.includes(profile.avatar_color)
        || !SKIN_TONES.includes(profile.skin_tone)
        || !HAIR_COLORS.includes(profile.hair_color)
        || !HAIR_STYLES.includes(profile.hair_style)) return;
    const roomId = socket.data.roomId;
    if (!roomId) return;
    const player = roomPlayers.get(roomId)?.get(socket.id);
    if (!player) return;
    Object.assign(player, {
      avatarColor: profile.avatar_color,
      skinTone: profile.skin_tone,
      hairColor: profile.hair_color,
      hairStyle: profile.hair_style,
    });
    io.to(roomId).emit("player:profile", {
      id: user.id,
      avatarColor: profile.avatar_color,
      skinTone: profile.skin_tone,
      hairColor: profile.hair_color,
      hairStyle: profile.hair_style,
    });
  });

  socket.on("chat:send", (rawMessage, callback) => {
    const acknowledge = typeof callback === "function" ? callback : () => {};
    const text = typeof rawMessage === "string" ? rawMessage.trim() : "";
    if (!socket.data.roomId || !text || text.length > 240) {
      return acknowledge({ error: "Wiadomość musi mieć od 1 do 240 znaków." });
    }
    if (!canAct(socket, "chat", 1, 1_500)) {
      return acknowledge({ error: "Poczekaj chwilę przed kolejną wiadomością." });
    }
    const currentUser = statements.userById.get(user.id);
    if (currentUser.muted_until > Date.now()) {
      return acknowledge({ error: "Twoje konto jest obecnie wyciszone." });
    }
    const message = {
      userId: user.id,
      username: user.username,
      text,
      timestamp: Date.now(),
    };
    io.to(socket.data.roomId).emit("chat:message", message);
    return acknowledge({ ok: true });
  });

  socket.on("disconnect", () => {
    const roomId = socket.data.roomId;
    if (!roomId) return;
    const players = roomPlayers.get(roomId);
    players?.delete(socket.id);
    socket.to(roomId).emit("player:left", { id: user.id });
    io.to(roomId).emit("room:count", players?.size || 0);
  });
});

const dist = path.join(root, "dist");
if (fs.existsSync(dist)) {
  app.use(express.static(dist, { index: false, maxAge: "1h" }));
  app.get("/{*path}", (_request, response) => response.sendFile(path.join(dist, "index.html")));
}

app.use((error, _request, response, _next) => {
  console.error(error);
  if (response.headersSent) return;
  response.status(500).json({ error: "Wystąpił nieoczekiwany błąd serwera." });
});

server.listen(port, "0.0.0.0", () => {
  console.info(`Wyspy API listening on port ${port}`);
});

function shutdown() {
  io.close();
  server.close(() => {
    db.close();
    process.exit(0);
  });
  setTimeout(() => process.exit(1), 10_000).unref();
}
process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);
