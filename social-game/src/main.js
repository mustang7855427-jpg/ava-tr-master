import Phaser from "phaser";
import { io } from "socket.io-client";
import { api, postJson } from "./api.js";
import { IslandScene } from "./game-scene.js";
import "./style.css";

const byId = (id) => document.getElementById(id);
const views = {
  auth: byId("auth-view"),
  world: byId("world-view"),
  admin: byId("admin-view"),
};
let user = null;
let socket = null;
let game = null;
let currentRoom = null;
let furnitureCatalog = [];
let registerMode = false;
let selectedFurniture = null;
let currentPlayers = [];
const avatarOptions = {
  avatarColor: ["#5aaab6", "#e98773", "#9d83c5", "#e5aa54", "#629b72"],
  skinTone: ["#f5d0b2", "#e7b08d", "#c98562", "#9c624a", "#654334"],
  hairColor: ["#42332f", "#754b35", "#c18a48", "#bd5748", "#403d62"],
  hairStyle: ["short", "curly", "bun"],
};
const hairStyleNames = { short: "Krótka", curly: "Kręcona", bun: "Kok" };

function showView(name) {
  for (const [key, element] of Object.entries(views)) {
    element.hidden = key !== name;
  }
}

function setFeedback(element, message, isError = false) {
  element.textContent = message;
  element.classList.toggle("is-error", isError);
}

function escapeText(value) {
  const node = document.createElement("span");
  node.textContent = value;
  return node.innerHTML;
}

function showToast(message) {
  const toast = byId("toast");
  toast.textContent = message;
  toast.classList.add("visible");
  window.clearTimeout(showToast.timeout);
  showToast.timeout = window.setTimeout(() => toast.classList.remove("visible"), 2800);
}

async function enterWorld(nextUser) {
  updateUser(nextUser);
  byId("player-label").innerHTML =
    `<span class="avatar-dot">${escapeText(user.username.slice(0, 1).toUpperCase())}</span>` +
    `<span>${escapeText(user.username)}</span>` +
    `<span id="coin-balance" class="player-coins" aria-label="Monety"></span>` +
    `<button id="player-logout" class="player-logout" type="button">Wyloguj</button>`;
  byId("coin-balance").textContent = `🟡 ${user.coins}`;
  byId("player-logout").addEventListener("click", logout);
  byId("admin-open").hidden = user.role !== "admin";
  showView("world");
  await loadWorld();
}

function updateUser(nextUser) {
  user = nextUser;
  const balance = byId("coin-balance");
  if (balance) balance.textContent = `🟡 ${user.coins}`;
  const rewardButton = byId("daily-reward");
  if (rewardButton) {
    rewardButton.disabled = !user.dailyRewardAvailable;
    rewardButton.textContent = user.dailyRewardAvailable
      ? "Odbierz 100 dziennych monet" : "Nagroda dzienna odebrana";
  }
  if (furnitureCatalog.length) renderFurniture();
  renderAvatarColors();
  activeScene()?.setLocalAppearance(user);
}

function renderAvatarColors() {
  if (!user) return;
  for (const [field, values] of Object.entries(avatarOptions)) {
    const containerId = {
      avatarColor: "avatar-colors",
      skinTone: "skin-tones",
      hairColor: "hair-colors",
      hairStyle: "hair-styles",
    }[field];
    const container = byId(containerId);
    if (!container) continue;
    container.innerHTML = values.map((value) => field === "hairStyle"
      ? `<button class="hair-style-button" type="button" data-value="${value}"
          aria-pressed="${user[field] === value}">${hairStyleNames[value]}</button>`
      : `<button class="avatar-color" type="button" data-value="${value}"
          style="--avatar-color:${value}" aria-label="Ustaw ${container.getAttribute("aria-label")}: ${value}"
          aria-pressed="${user[field] === value}"></button>`).join("");
    container.querySelectorAll("[data-value]").forEach((button) => {
      button.addEventListener("click", async () => {
        try {
          const data = await api("/api/auth/profile", {
            method: "PATCH",
            body: JSON.stringify({ [field]: button.dataset.value }),
          });
          updateUser(data.user);
          socket?.emit("player:profile");
        } catch (error) {
          showToast(error.message);
        }
      });
    });
  }
}

async function loadWorld() {
  try {
    const [roomData, catalogData] = await Promise.all([
      api("/api/rooms"),
      api("/api/catalog"),
    ]);
    furnitureCatalog = catalogData.furniture;
    renderFurniture();
    renderRooms(roomData.rooms);
    if (!game) {
      game = new Phaser.Game({
        type: Phaser.AUTO,
        parent: "game-container",
        width: 900,
        height: 560,
        backgroundColor: "#c8f0ed",
        scale: {
          mode: Phaser.Scale.RESIZE,
          autoCenter: Phaser.Scale.CENTER_BOTH,
          min: { width: 320, height: 300 },
          max: { width: 1400, height: 900 },
        },
        input: { activePointers: 1 },
        scene: [],
        render: { antialias: true, pixelArt: false, roundPixels: false },
      });
      const scene = new IslandScene(sendPosition, placeFurniture);
      game.scene.add("IslandScene", scene, true);
      scene.setPlayerId(user.id);
      scene.setCatalog(furnitureCatalog);
      scene.setDeleteFurnitureHandler(removeFurniture);
    }
    activeScene()?.setLocalAppearance(user);
    connectSocket();
    await joinRoom(roomData.rooms[0].id);
  } catch (error) {
    showToast(error.message);
    if (error.message.includes("Zaloguj")) logout();
  }
}

function connectSocket() {
  if (socket?.connected) return;
  if (!socket) {
    socket = io({ transports: ["websocket", "polling"], withCredentials: true });
    socket.on("connect", () => {
      byId("chat-status").textContent = "połączono";
      byId("chat-status").classList.add("connected");
      if (currentRoom) joinRoom(currentRoom.id);
    });
    socket.on("disconnect", () => {
      byId("chat-status").textContent = "ponowne łączenie…";
      byId("chat-status").classList.remove("connected");
    });
    socket.on("connect_error", (error) => {
      byId("chat-status").textContent = "offline";
      showToast(error.message || "Nie udało się połączyć z pokojem.");
    });
    socket.on("player:joined", (player) => {
      if (!currentPlayers.some((current) => current.id === player.id)) {
        currentPlayers.push(player);
        activeScene()?.setPlayers(currentPlayers);
      }
    });
    socket.on("player:moved", (position) => {
      const player = currentPlayers.find((item) => item.id === position.id);
      if (player) Object.assign(player, position);
      activeScene()?.setPlayers(currentPlayers);
    });
    socket.on("player:profile", (appearance) => {
      const player = currentPlayers.find((item) => item.id === appearance.id);
      if (player) Object.assign(player, appearance);
      activeScene()?.setPlayers(currentPlayers);
    });
    socket.on("player:left", ({ id }) => {
      currentPlayers = currentPlayers.filter((player) => player.id !== id);
      activeScene()?.setPlayers(currentPlayers);
    });
    socket.on("room:count", (count) => {
      byId("room-count").textContent = `${count} ${count === 1 ? "gracz" : "graczy"}`;
    });
    socket.on("chat:message", addChatMessage);
    socket.on("furniture:added", (item) => activeScene()?.addFurniture(item));
    socket.on("furniture:removed", ({ id }) => activeScene()?.removeFurniture(id));
    socket.on("furniture:cleared", () => activeScene()?.clearFurniture());
    socket.on("inventory:refresh", async () => {
      try {
        const data = await api("/api/auth/me");
        updateUser(data.user);
      } catch (error) {
        showToast(error.message);
      }
    });
    socket.on("account:banned", () => {
      showToast("Konto zostało zablokowane przez administratora.");
      logout();
    });
    socket.on("account:refresh", async () => {
      try {
        const data = await api("/api/auth/me");
        updateUser(data.user);
        if (user.role !== "admin") byId("admin-open").hidden = true;
      } catch (error) {
        showToast(error.message);
        logout();
      }
    });
  }
  socket.connect();
}

function activeScene() {
  return game?.scene.getScene("IslandScene");
}

async function joinRoom(roomId) {
  if (!socket?.connected) return;
  const changedRoom = currentRoom?.id !== roomId;
  socket.emit("room:join", roomId, (result) => {
    if (result?.error) return showToast(result.error);
    currentRoom = result.room;
    currentPlayers = result.players || [];
    byId("room-title").textContent = currentRoom.name;
    byId("room-count").textContent =
      `${result.count} ${result.count === 1 ? "gracz" : "graczy"}`;
    byId("chat-messages").replaceChildren();
    activeScene()?.setRoom(currentRoom);
    activeScene()?.setPlayers(currentPlayers);
    activeScene()?.setFurnitureItems(result.furniture || []);
    document.querySelectorAll(".room-button").forEach((button) => {
      button.classList.toggle("active", button.dataset.room === roomId);
    });
    if (changedRoom) byId("chat-input").focus();
  });
}

function renderRooms(rooms) {
  byId("room-list").innerHTML = rooms.map((room) => `
    <button class="room-button${currentRoom?.id === room.id ? " active" : ""}"
      type="button" data-room="${escapeText(room.id)}">
      <span class="room-icon">${room.theme === "beach" ? "≈" : room.theme === "cafe" ? "☕" : "✦"}</span>
      <span class="room-copy"><strong>${escapeText(room.name)}</strong>
        <small>${escapeText(room.description)}</small></span>
      <span class="room-online">${room.online}</span>
    </button>`).join("");
  byId("room-list").querySelectorAll(".room-button").forEach((button) => {
    button.addEventListener("click", () => joinRoom(button.dataset.room));
  });
}

function renderFurniture() {
  byId("furniture-list").innerHTML = furnitureCatalog.map((item) => `
    <button class="furniture-item${selectedFurniture?.id === item.id ? " selected" : ""}"
      type="button" data-furniture="${escapeText(item.id)}">
      <span class="furniture-swatch" style="--swatch:${escapeText(item.color)}"></span>
      <span>${escapeText(item.name)}</span>
      <small>${escapeText(item.category)}</small>
      <small class="furniture-price">${item.price} monet</small>
      <small class="furniture-quantity">W plecaku: ${inventoryQuantity(item.id)}</small>
    </button>`).join("");
  byId("furniture-list").querySelectorAll(".furniture-item").forEach((button) => {
    button.addEventListener("click", async () => {
      const item = furnitureCatalog.find((furniture) => furniture.id === button.dataset.furniture);
      if (inventoryQuantity(item.id) === 0) {
        try {
          const data = await postJson("/api/shop/purchase", { catalogId: item.id });
          updateUser(data.user);
          showToast(`Kupiono: ${item.name}.`);
        } catch (error) {
          showToast(error.message);
        }
        return;
      }
      selectedFurniture = item;
      activeScene()?.setFurniture(selectedFurniture);
      renderFurniture();
      showToast("Kliknij miejsce w pokoju, aby postawić mebel.");
    });
  });
}

function inventoryQuantity(catalogId) {
  return user?.inventory?.find((item) => item.catalog_id === catalogId)?.quantity || 0;
}

function addChatMessage(message) {
  const list = byId("chat-messages");
  const item = document.createElement("li");
  item.className = `chat-message${message.system ? " system-message" : ""}`;
  const time = new Date(message.timestamp).toLocaleTimeString("pl-PL", {
    hour: "2-digit", minute: "2-digit",
  });
  item.innerHTML = `<span class="chat-meta"><strong>${escapeText(message.username)}</strong><time>${time}</time></span>` +
    `<span class="chat-text">${escapeText(message.text)}</span>`;
  list.append(item);
  if (list.children.length > 100) list.firstElementChild.remove();
  list.scrollTop = list.scrollHeight;
}

function sendPosition(position) {
  socket?.emit("player:move", position);
}

async function placeFurniture({ x, y, catalogId }) {
  if (!currentRoom) return;
  try {
    const data = await postJson("/api/furniture", {
      roomId: currentRoom.id, catalogId, x, y,
    });
    updateUser(data.user);
    selectedFurniture = null;
    activeScene()?.setFurniture(null);
    renderFurniture();
    activeScene()?.addFurniture(data.furniture);
  } catch (error) {
    showToast(error.message);
  }
}

async function removeFurniture(id) {
  try {
    const response = await fetch(`/api/furniture/${id}`, {
      method: "DELETE",
      credentials: "same-origin",
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Nie udało się usunąć mebla.");
    if (data.user) updateUser(data.user);
  } catch (error) {
    showToast(error.message);
  }
}

async function logout() {
  socket?.disconnect();
  if (game) {
    game.destroy(true);
    game = null;
  }
  try {
    await postJson("/api/auth/logout", {});
  } catch {
    // The local view is reset even if the session has already expired.
  }
  user = null;
  currentRoom = null;
  byId("player-label").replaceChildren();
  showView("auth");
}

async function loadAdmin() {
  try {
    const data = await api("/api/admin/overview");
    byId("stat-online").textContent = data.online;
    byId("stat-users").textContent = data.users.length;
    byId("stat-rooms").textContent = data.rooms.length;
    byId("admin-rooms").innerHTML = data.rooms.map((room) => `
      <button type="button" data-clear-room="${escapeText(room.id)}">
        Opróżnij: ${escapeText(room.name)} (${room.online} online)
      </button>`).join("");
    byId("admin-rooms").querySelectorAll("[data-clear-room]").forEach((button) => {
      button.addEventListener("click", async () => {
        if (!window.confirm("Usunąć wszystkie meble z tego pokoju? Przedmioty wrócą do plecaków właścicieli.")) return;
        try {
          const result = await api(`/api/admin/rooms/${button.dataset.clearRoom}/furniture`, {
            method: "DELETE",
          });
          showToast(`Usunięto meble: ${result.cleared}.`);
          if (currentRoom?.id === button.dataset.clearRoom) activeScene()?.clearFurniture();
        } catch (error) {
          showToast(error.message);
        }
      });
    });
    byId("admin-users").innerHTML = data.users.map((account) => `
      <tr>
        <td><strong>${escapeText(account.username)}</strong><small>#${account.id}</small></td>
        <td><select aria-label="Ranga ${escapeText(account.username)}" data-role-id="${account.id}">
          <option value="player"${account.role === "player" ? " selected" : ""}>Gracz</option>
          <option value="admin"${account.role === "admin" ? " selected" : ""}>Administrator</option>
        </select></td>
        <td class="admin-actions">
          <button type="button" data-action="${account.muted_until > Date.now() ? "unmute" : "mute"}"
            data-user-id="${account.id}">${account.muted_until > Date.now() ? "Odwycisz" : "Wycisz"}</button>
          <button type="button" data-action="${account.banned_until > Date.now() ? "unban" : "ban"}"
            data-user-id="${account.id}">${account.banned_until > Date.now() ? "Odblokuj" : "Zablokuj"}</button>
          <button type="button" data-action="coins" data-user-id="${account.id}">Monety</button>
          <button type="button" data-action="password" data-user-id="${account.id}">Hasło</button>
        </td>
      </tr>`).join("");
    byId("admin-users").querySelectorAll("[data-role-id]").forEach((select) => {
      select.addEventListener("change", async () => {
        try {
          await api(`/api/admin/users/${select.dataset.roleId}/role`, {
            method: "PATCH", body: JSON.stringify({ role: select.value }),
          });
          showToast("Zmieniono rangę gracza.");
        } catch (error) {
          showToast(error.message);
          loadAdmin();
        }
      });
    });
    byId("admin-users").querySelectorAll("[data-action]").forEach((button) => {
      button.addEventListener("click", async () => {
        const action = button.dataset.action;
        if (action === "coins") {
          const amount = Number(window.prompt("Ile monet przyznać temu graczowi?"));
          if (!Number.isSafeInteger(amount) || amount < 1 || amount > 100_000) return;
          try {
            await postJson(`/api/admin/users/${button.dataset.userId}/coins`, { amount });
            showToast("Przyznano monety graczowi.");
          } catch (error) {
            showToast(error.message);
          }
          return;
        }
        if (action === "password") {
          const password = window.prompt("Wpisz nowe hasło (co najmniej 10 znaków):");
          if (!password) return;
          try {
            await postJson(`/api/admin/users/${button.dataset.userId}/password`, { password });
            showToast("Hasło zostało zmienione. Gracz musi zalogować się ponownie.");
          } catch (error) {
            showToast(error.message);
          }
          return;
        }
        const confirmText = action === "ban" ? "Zablokować"
          : action === "unban" ? "Odblokować"
            : action === "unmute" ? "Cofnąć wyciszenie" : "Wyciszyć";
        if (!window.confirm(`${confirmText} tego gracza?`)) return;
        try {
          await postJson(`/api/admin/users/${button.dataset.userId}/moderation`, {
            action, minutes: 10,
          });
          showToast(action === "ban" ? "Konto czasowo zablokowano."
            : action === "unban" ? "Blokada konta została cofnięta."
              : action === "unmute" ? "Wyciszenie zostało cofnięte." : "Gracza wyciszono.");
          loadAdmin();
        } catch (error) {
          showToast(error.message);
        }
      });
    });
  } catch (error) {
    showToast(error.message);
    if (error.message.includes("uprawnień")) showView("world");
  }
}

byId("auth-switch").addEventListener("click", () => {
  registerMode = !registerMode;
  byId("auth-title").textContent = registerMode ? "Stwórz swój profil" : "Miło Cię widzieć!";
  byId("auth-submit").textContent = registerMode ? "Utwórz konto" : "Wejdź na wyspę";
  byId("auth-switch").textContent = registerMode ? "Mam już konto" : "Załóż nowe konto";
  byId("auth-form").elements.password.autocomplete =
    registerMode ? "new-password" : "current-password";
  byId("auth-message").textContent = registerMode
    ? "Użyj unikalnego hasła o długości co najmniej 10 znaków."
    : "";
});

byId("auth-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const endpoint = registerMode ? "/api/auth/register" : "/api/auth/login";
  byId("auth-submit").disabled = true;
  setFeedback(byId("auth-message"), "Chwila…");
  try {
    const data = await postJson(endpoint, {
      username: form.get("username"),
      password: form.get("password"),
    });
    event.currentTarget.reset();
    await enterWorld(data.user);
  } catch (error) {
    setFeedback(byId("auth-message"), error.message, true);
  } finally {
    byId("auth-submit").disabled = false;
  }
});

byId("chat-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = byId("chat-input");
  const text = input.value.trim();
  if (!text || !socket?.connected) return;
  socket.emit("chat:send", text, (result) => {
    if (result?.error) showToast(result.error);
  });
  input.value = "";
  input.focus();
});

byId("logout").addEventListener("click", logout);
byId("clear-placement").addEventListener("click", () => {
  selectedFurniture = null;
  activeScene()?.setFurniture(null);
  renderFurniture();
});
byId("daily-reward").addEventListener("click", async () => {
  try {
    const data = await postJson("/api/rewards/daily", {});
    updateUser(data.user);
    showToast("Odebrano 100 monet. Wróć jutro po kolejne!");
  } catch (error) {
    showToast(error.message);
  }
});
byId("admin-open").addEventListener("click", async () => {
  showView("admin");
  await loadAdmin();
});
byId("admin-close").addEventListener("click", () => showView("world"));
byId("broadcast-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await postJson("/api/admin/broadcast", { message: byId("broadcast-text").value });
    byId("broadcast-text").value = "";
    setFeedback(byId("admin-message"), "Ogłoszenie wysłano do wszystkich pokojów.");
  } catch (error) {
    setFeedback(byId("admin-message"), error.message, true);
  }
});

document.addEventListener("visibilitychange", () => {
  if (!document.hidden && user && socket && !socket.connected) socket.connect();
});

api("/api/auth/me")
  .then((data) => enterWorld(data.user))
  .catch(() => showView("auth"));
