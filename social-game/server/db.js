import fs from "node:fs";
import path from "node:path";
import Database from "better-sqlite3";

const databasePath = path.resolve(process.env.DATABASE_PATH || "./data/world.sqlite");
fs.mkdirSync(path.dirname(databasePath), { recursive: true });

export const db = new Database(databasePath);
db.pragma("journal_mode = WAL");
db.pragma("foreign_keys = ON");

db.exec(`
  CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'player' CHECK(role IN ('player', 'admin')),
    created_at INTEGER NOT NULL,
    muted_until INTEGER NOT NULL DEFAULT 0,
    banned_until INTEGER NOT NULL DEFAULT 0,
    coins INTEGER NOT NULL DEFAULT 300,
    avatar_color TEXT NOT NULL DEFAULT '#5aaab6',
    skin_tone TEXT NOT NULL DEFAULT '#f5d0b2',
    hair_color TEXT NOT NULL DEFAULT '#42332f',
    hair_style TEXT NOT NULL DEFAULT 'short',
    daily_reward_at INTEGER NOT NULL DEFAULT 0
  );
  CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at INTEGER NOT NULL
  );
  CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires_at);
  CREATE TABLE IF NOT EXISTS furniture (
    id INTEGER PRIMARY KEY,
    room_id TEXT NOT NULL,
    catalog_id TEXT NOT NULL,
    x REAL NOT NULL,
    y REAL NOT NULL,
    placed_by INTEGER NOT NULL REFERENCES users(id),
    created_at INTEGER NOT NULL
  );
  CREATE INDEX IF NOT EXISTS furniture_room ON furniture(room_id);
  CREATE TABLE IF NOT EXISTS inventory (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    catalog_id TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 0 CHECK(quantity >= 0),
    PRIMARY KEY (user_id, catalog_id)
  );
`);

const userColumns = new Set(
  db.prepare("PRAGMA table_info(users)").all().map((column) => column.name),
);
if (!userColumns.has("coins")) {
  db.exec("ALTER TABLE users ADD COLUMN coins INTEGER NOT NULL DEFAULT 300");
}
if (!userColumns.has("avatar_color")) {
  db.exec("ALTER TABLE users ADD COLUMN avatar_color TEXT NOT NULL DEFAULT '#5aaab6'");
}
if (!userColumns.has("daily_reward_at")) {
  db.exec("ALTER TABLE users ADD COLUMN daily_reward_at INTEGER NOT NULL DEFAULT 0");
}
if (!userColumns.has("skin_tone")) {
  db.exec("ALTER TABLE users ADD COLUMN skin_tone TEXT NOT NULL DEFAULT '#f5d0b2'");
}
if (!userColumns.has("hair_color")) {
  db.exec("ALTER TABLE users ADD COLUMN hair_color TEXT NOT NULL DEFAULT '#42332f'");
}
if (!userColumns.has("hair_style")) {
  db.exec("ALTER TABLE users ADD COLUMN hair_style TEXT NOT NULL DEFAULT 'short'");
}

export const statements = {
  userByName: db.prepare("SELECT * FROM users WHERE username = ?"),
  userById: db.prepare("SELECT * FROM users WHERE id = ?"),
  createUser: db.prepare(
    "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
  ),
  session: db.prepare(
    `SELECT users.* FROM sessions JOIN users ON users.id = sessions.user_id
     WHERE sessions.token_hash = ? AND sessions.expires_at > ?`,
  ),
  createSession: db.prepare(
    "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
  ),
  deleteSession: db.prepare("DELETE FROM sessions WHERE token_hash = ?"),
  deleteExpiredSessions: db.prepare("DELETE FROM sessions WHERE expires_at <= ?"),
  furnitureInRoom: db.prepare("SELECT * FROM furniture WHERE room_id = ? ORDER BY id"),
  furnitureById: db.prepare("SELECT * FROM furniture WHERE id = ?"),
  furnitureCountInRoom: db.prepare("SELECT COUNT(*) AS count FROM furniture WHERE room_id = ?"),
  addFurniture: db.prepare(
    `INSERT INTO furniture (room_id, catalog_id, x, y, placed_by, created_at)
     VALUES (?, ?, ?, ?, ?, ?)`,
  ),
  removeFurniture: db.prepare("DELETE FROM furniture WHERE id = ?"),
  clearRoomFurniture: db.prepare("DELETE FROM furniture WHERE room_id = ?"),
  countUsers: db.prepare("SELECT COUNT(*) AS count FROM users"),
  adminExists: db.prepare("SELECT 1 FROM users WHERE role = 'admin' LIMIT 1"),
  allUsers: db.prepare(
    `SELECT id, username, role, created_at, muted_until, banned_until
     FROM users ORDER BY id DESC LIMIT 200`,
  ),
  updateRole: db.prepare("UPDATE users SET role = ? WHERE id = ?"),
  updateModeration: db.prepare(
    "UPDATE users SET muted_until = ?, banned_until = ? WHERE id = ?",
  ),
  updatePassword: db.prepare("UPDATE users SET password_hash = ? WHERE id = ?"),
  updateAvatar: db.prepare(
    `UPDATE users SET avatar_color = ?, skin_tone = ?, hair_color = ?, hair_style = ?
     WHERE id = ?`,
  ),
  adjustCoins: db.prepare("UPDATE users SET coins = coins + ? WHERE id = ?"),
  claimDailyReward: db.prepare(
    "UPDATE users SET coins = coins + 100, daily_reward_at = ? WHERE id = ?",
  ),
  inventoryCount: db.prepare(
    "SELECT quantity FROM inventory WHERE user_id = ? AND catalog_id = ?",
  ),
  setInventory: db.prepare(
    `INSERT INTO inventory (user_id, catalog_id, quantity) VALUES (?, ?, ?)
     ON CONFLICT(user_id, catalog_id) DO UPDATE SET quantity = excluded.quantity`,
  ),
  userInventory: db.prepare(
    "SELECT catalog_id, quantity FROM inventory WHERE user_id = ?",
  ),
};

const now = Date.now();
statements.deleteExpiredSessions.run(now);

export function publicUser(user) {
  return {
    id: user.id,
    username: user.username,
    role: user.role,
    mutedUntil: user.muted_until,
    bannedUntil: user.banned_until,
    coins: user.coins,
    avatarColor: user.avatar_color,
    skinTone: user.skin_tone,
    hairColor: user.hair_color,
    hairStyle: user.hair_style,
    inventory: statements.userInventory.all(user.id),
    dailyRewardAvailable: user.daily_reward_at <= Date.now() - 24 * 60 * 60 * 1000,
  };
}
