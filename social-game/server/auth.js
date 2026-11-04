import crypto from "node:crypto";
import bcrypt from "bcryptjs";
import { Router } from "express";
import { rateLimit } from "express-rate-limit";
import { db, publicUser, statements } from "./db.js";
import { AVATAR_COLORS, HAIR_COLORS, HAIR_STYLES, SKIN_TONES } from "./rooms.js";

const SESSION_COOKIE = "island_session";
const sessionDays = Math.min(30, Math.max(1, Number(process.env.SESSION_DAYS) || 14));
const sessionLifetime = sessionDays * 24 * 60 * 60 * 1000;

function hashToken(token) {
  return crypto.createHash("sha256").update(token).digest("hex");
}

function safeEqual(left, right) {
  const leftBuffer = Buffer.from(left);
  const rightBuffer = Buffer.from(right);
  return leftBuffer.length === rightBuffer.length
    && crypto.timingSafeEqual(leftBuffer, rightBuffer);
}

export function readSessionToken(request) {
  const cookie = request.headers.cookie || "";
  const part = cookie.split(";").map((value) => value.trim())
    .find((value) => value.startsWith(`${SESSION_COOKIE}=`));
  if (!part) return null;
  try {
    return decodeURIComponent(part.slice(SESSION_COOKIE.length + 1));
  } catch {
    return null;
  }
}

export function getUserForToken(token) {
  if (!token || token.length > 200) return null;
  const user = statements.session.get(hashToken(token), Date.now());
  if (!user || user.banned_until > Date.now()) return null;
  return user;
}

export function requireUser(request, response, next) {
  const user = getUserForToken(readSessionToken(request));
  if (!user) return response.status(401).json({ error: "Zaloguj się ponownie." });
  request.user = user;
  return next();
}

export function requireAdmin(request, response, next) {
  if (request.user?.role !== "admin") {
    return response.status(403).json({ error: "Ta czynność wymaga uprawnień administratora." });
  }
  return next();
}

function setSession(response, userId) {
  const token = crypto.randomBytes(32).toString("base64url");
  statements.createSession.run(
    hashToken(token),
    userId,
    Date.now() + sessionLifetime,
  );
  response.cookie(SESSION_COOKIE, token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "strict",
    path: "/",
    maxAge: sessionLifetime,
  });
}

function validateCredentials(username, password) {
  return typeof username === "string"
    && /^[\p{L}\p{N}_ -]{3,24}$/u.test(username.trim())
    && typeof password === "string"
    && password.length >= 10
    && password.length <= 128;
}

const authLimit = rateLimit({
  windowMs: 15 * 60 * 1000,
  limit: 12,
  standardHeaders: "draft-8",
  legacyHeaders: false,
  message: { error: "Zbyt wiele prób logowania. Spróbuj ponownie za chwilę." },
});

export function createAuthRouter() {
  const router = Router();

  router.post("/register", authLimit, (request, response) => {
    if (process.env.ALLOW_REGISTRATION === "false") {
      return response.status(403).json({ error: "Rejestracja jest obecnie wyłączona." });
    }
    const { username, password } = request.body || {};
    if (!validateCredentials(username, password)) {
      return response.status(400).json({
        error: "Nazwa może mieć 3–24 znaki. Hasło musi mieć od 10 do 128 znaków.",
      });
    }
    try {
      const result = statements.createUser.run(
        username.trim(),
        bcrypt.hashSync(password, 12),
        Date.now(),
      );
      setSession(response, Number(result.lastInsertRowid));
      const user = statements.userById.get(Number(result.lastInsertRowid));
      return response.status(201).json({ user: publicUser(user) });
    } catch (error) {
      if (error.code === "SQLITE_CONSTRAINT_UNIQUE") {
        return response.status(409).json({ error: "Ta nazwa gracza jest już zajęta." });
      }
      throw error;
    }
  });

  router.post("/login", authLimit, (request, response) => {
    const { username, password } = request.body || {};
    if (typeof username !== "string" || typeof password !== "string"
        || password.length > 128) {
      return response.status(400).json({ error: "Podaj nazwę gracza i hasło." });
    }
    const user = statements.userByName.get(username.trim());
    if (!user || !bcrypt.compareSync(password, user.password_hash)) {
      return response.status(401).json({ error: "Nieprawidłowa nazwa lub hasło." });
    }
    if (user.banned_until > Date.now()) {
      return response.status(403).json({ error: "To konto jest czasowo zablokowane." });
    }
    setSession(response, user.id);
    return response.json({ user: publicUser(user) });
  });

  router.post("/logout", requireUser, (request, response) => {
    const token = readSessionToken(request);
    if (token) statements.deleteSession.run(hashToken(token));
    response.clearCookie(SESSION_COOKIE, {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "strict",
      path: "/",
    });
    return response.json({ ok: true });
  });

  router.get("/me", requireUser, (request, response) => {
    return response.json({ user: publicUser(request.user) });
  });

  router.patch("/profile", requireUser, (request, response) => {
    const body = request.body || {};
    const color = body.avatarColor ?? request.user.avatar_color;
    const skinTone = body.skinTone ?? request.user.skin_tone;
    const hairColor = body.hairColor ?? request.user.hair_color;
    const hairStyle = body.hairStyle ?? request.user.hair_style;
    if (!AVATAR_COLORS.includes(color) || !SKIN_TONES.includes(skinTone)
        || !HAIR_COLORS.includes(hairColor) || !HAIR_STYLES.includes(hairStyle)) {
      return response.status(400).json({ error: "Wybierz prawidłowe opcje wyglądu awatara." });
    }
    statements.updateAvatar.run(color, skinTone, hairColor, hairStyle, request.user.id);
    const updatedUser = statements.userById.get(request.user.id);
    return response.json({ user: publicUser(updatedUser) });
  });

  router.post("/claim-admin", authLimit, (request, response) => {
    const expectedKey = process.env.ADMIN_SETUP_KEY || "";
    const suppliedKey = typeof request.body?.setupKey === "string"
      ? request.body.setupKey : "";
    if (expectedKey.length < 32 || !safeEqual(suppliedKey, expectedKey)) {
      return response.status(403).json({ error: "Brak prawidłowego klucza konfiguracji administratora." });
    }
    const { username, password } = request.body || {};
    if (!validateCredentials(username, password)) {
      return response.status(400).json({ error: "Nieprawidłowa nazwa lub hasło." });
    }
    const claimAdmin = db.transaction(() => {
      if (statements.adminExists.get()) {
        return { error: "Konto administratora zostało już skonfigurowane." };
      }
      let user = statements.userByName.get(username.trim());
      if (!user) {
        const result = statements.createUser.run(
          username.trim(), bcrypt.hashSync(password, 12), Date.now(),
        );
        user = statements.userById.get(Number(result.lastInsertRowid));
      } else if (!bcrypt.compareSync(password, user.password_hash)) {
        return { error: "Podana nazwa należy do konta z innym hasłem." };
      }
      statements.updateRole.run("admin", user.id);
      return { user: statements.userById.get(user.id) };
    });
    const result = claimAdmin();
    if (result.error) return response.status(409).json({ error: result.error });
    setSession(response, result.user.id);
    return response.status(201).json({ user: publicUser(result.user) });
  });

  return router;
}
