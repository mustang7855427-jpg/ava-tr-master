import Phaser from "phaser";

const PALETTE = {
  sand: 0xf3ddb0,
  sandDark: 0xdfc38c,
  sea: 0x7cc9d0,
  seaDark: 0x48aab5,
  grass: 0x8bc985,
  grassDark: 0x5cae78,
  wood: 0x9b6849,
  ink: 0x31485a,
  white: 0xfffcf4,
};

function colorNumber(value, fallback = 0x588f73) {
  if (typeof value !== "string" || !/^#[0-9a-f]{6}$/i.test(value)) return fallback;
  return Number.parseInt(value.slice(1), 16);
}

export class IslandScene extends Phaser.Scene {
  constructor(onMove, onFurniturePlace) {
    super("IslandScene");
    this.onMove = onMove;
    this.onFurniturePlace = onFurniturePlace;
    this.players = new Map();
    this.roomPlayers = new Map();
    this.furnitureSprites = new Map();
    this.placedFurniture = [];
    this.activeFurniture = null;
    this.destination = null;
    this.playerX = 0.5;
    this.playerY = 0.68;
    this.appearance = {
      avatarColor: "#5aaab6",
      skinTone: "#f5d0b2",
      hairColor: "#42332f",
      hairStyle: "short",
    };
  }

  create() {
    this.drawRoom();
    this.player = this.makeAvatar(this.playerX, this.playerY, true, "Ty", this.appearance);
    this.cursors = this.input.keyboard.createCursorKeys();
    this.keys = this.input.keyboard.addKeys("W,A,S,D");
    this.input.on("pointerdown", (pointer) => this.onRoomClick(pointer));
    this.input.keyboard.on("keydown-ESC", () => this.setFurniture(null));
    this.resizeHandler = () => this.drawRoom();
    this.scale.on("resize", this.resizeHandler);
  }

  drawRoom() {
    const width = this.scale.width;
    const height = this.scale.height;
    if (!width || !height) return;
    this.background?.destroy();
    this.background = null;
    if (this.textures.exists("room-background")) {
      this.textures.remove("room-background");
    }
    const graphics = this.make.graphics({ x: 0, y: 0, add: false });
    graphics.fillGradientStyle(0xc8f0ed, 0xc8f0ed, 0x91cfaa, 0x91cfaa, 1);
    graphics.fillRect(0, 0, width, height);
    graphics.fillStyle(PALETTE.sand, 1);
    graphics.fillEllipse(width * 0.5, height * 0.62, width * 0.76, height * 0.55);
    graphics.fillStyle(PALETTE.sandDark, 0.42);
    graphics.fillEllipse(width * 0.5, height * 0.79, width * 0.7, height * 0.13);
    graphics.fillStyle(PALETTE.white, 0.72);
    for (let index = 0; index < 5; index += 1) {
      const x = width * (0.12 + index * 0.18);
      graphics.fillCircle(x, height * (0.1 + (index % 2) * 0.06), 13);
      graphics.fillCircle(x + 13, height * (0.1 + (index % 2) * 0.06), 18);
      graphics.fillCircle(x + 29, height * (0.1 + (index % 2) * 0.06), 12);
    }
    graphics.fillStyle(PALETTE.grassDark, 0.75);
    for (let index = 0; index < 7; index += 1) {
      const x = width * (0.07 + index * 0.145);
      const y = height * (0.5 + (index % 2) * 0.025);
      graphics.fillEllipse(x, y, 34, 20);
    }
    graphics.fillStyle(PALETTE.wood, 1);
    graphics.fillRoundedRect(width * 0.44, height * 0.27, width * 0.12, height * 0.12, 9);
    graphics.fillStyle(0xd58666, 1);
    graphics.fillTriangle(width * 0.42, height * 0.29, width * 0.5, height * 0.21, width * 0.58, height * 0.29);
    graphics.fillStyle(0x6a4439, 1);
    graphics.fillRoundedRect(width * 0.485, height * 0.32, width * 0.03, height * 0.07, 3);
    graphics.generateTexture("room-background", width, height);
    graphics.destroy();

    this.background = this.add.image(0, 0, "room-background").setOrigin(0);
    this.background.setDisplaySize(width, height);
    this.children.sendToBack(this.background);
    this.positionActors();
    this.positionFurniture();
  }

  makeAvatar(x, y, local = false, name = "", appearance = {}) {
    const container = this.add.container(x * this.scale.width, y * this.scale.height);
    const shadow = this.add.ellipse(0, 23, 35, 10, 0x31524c, 0.22);
    const body = this.add.ellipse(
      0, 8, 24, 31, colorNumber(appearance.avatarColor, local ? 0x57a9c1 : 0xe7a454),
    );
    const head = this.add.circle(0, -13, 15, colorNumber(appearance.skinTone, 0xf5d0b2));
    const hair = this.makeHair(appearance.hairStyle, appearance.hairColor);
    const eye = this.add.circle(5, -12, 1.5, PALETTE.ink);
    const label = this.add.text(0, 34, name || (local ? "Ty" : ""), {
      fontFamily: "Trebuchet MS, sans-serif",
      fontSize: "12px",
      color: "#35485a",
      backgroundColor: "#fff9e8dd",
      padding: { x: 5, y: 2 },
    }).setOrigin(0.5, 0);
    container.add([shadow, body, head, hair, eye, label]);
    container.setDepth(y * 1000 + (local ? 1 : 0));
    container.appearance = { ...appearance };
    return container;
  }

  makeHair(style, color) {
    const hair = this.add.container(0, -24);
    const fill = colorNumber(color, 0x42332f);
    if (style === "bun") {
      hair.add(this.add.circle(0, -10, 8, fill));
      hair.add(this.add.ellipse(0, 0, 27, 15, fill));
    } else if (style === "curly") {
      for (const [x, y, radius] of [
        [-10, 2, 7], [0, -2, 8], [10, 2, 7], [-6, -6, 6], [7, -7, 6],
      ]) {
        hair.add(this.add.circle(x, y, radius, fill));
      }
    } else {
      hair.add(this.add.ellipse(0, 0, 26, 13, fill));
    }
    return hair;
  }

  applyAppearance(avatar, appearance) {
    const previous = avatar.appearance || {};
    if (previous.avatarColor !== appearance.avatarColor) {
      avatar.list[1].setFillStyle(colorNumber(appearance.avatarColor, 0xe7a454));
    }
    if (previous.skinTone !== appearance.skinTone) {
      avatar.list[2].setFillStyle(colorNumber(appearance.skinTone, 0xf5d0b2));
    }
    if (previous.hairStyle !== appearance.hairStyle
        || previous.hairColor !== appearance.hairColor) {
      avatar.getAt(3).destroy();
      avatar.addAt(this.makeHair(appearance.hairStyle, appearance.hairColor), 3);
    }
    avatar.appearance = { ...appearance };
  }

  setRoom(room) {
    this.room = room;
    if (!this.background) return;
    const tint = room.theme === "beach" ? 0xd1f2eb
      : room.theme === "cafe" ? 0xf1dfbd : 0xc8f0ed;
    this.background.setTint(tint);
  }

  setPlayers(players) {
    this.roomPlayers = new Map(players.map((item) => [item.id, item]));
    const activeIds = new Set(players.map((item) => item.id));
    for (const [id, player] of this.players) {
      if (!activeIds.has(id)) {
        player.destroy();
        this.players.delete(id);
      }
    }
    for (const item of players) {
      if (item.id === this.playerId) continue;
      let avatar = this.players.get(item.id);
      if (!avatar) {
        avatar = this.makeAvatar(item.x, item.y, false, item.username, item);
        this.players.set(item.id, avatar);
      } else {
        this.applyAppearance(avatar, item);
      }
      this.placeActor(avatar, item.x, item.y);
    }
  }

  setPlayerId(id) {
    this.playerId = id;
  }

  setLocalAppearance(appearance) {
    this.appearance = { ...this.appearance, ...appearance };
    if (this.player) this.applyAppearance(this.player, this.appearance);
  }

  setFurnitureItems(items) {
    const activeIds = new Set(items.map((item) => item.id));
    for (const [id, sprite] of this.furnitureSprites) {
      if (!activeIds.has(id)) {
        sprite.destroy();
        this.furnitureSprites.delete(id);
      }
    }
    this.placedFurniture = items;
    this.positionFurniture();
  }

  addFurniture(item) {
    if (!this.placedFurniture.some((current) => current.id === item.id)) {
      this.placedFurniture.push(item);
      this.positionFurniture();
    }
  }

  removeFurniture(id) {
    this.furnitureSprites.get(id)?.destroy();
    this.furnitureSprites.delete(id);
    this.placedFurniture = this.placedFurniture.filter((item) => item.id !== id);
  }

  clearFurniture() {
    for (const sprite of this.furnitureSprites.values()) sprite.destroy();
    this.furnitureSprites.clear();
    this.placedFurniture = [];
  }

  positionFurniture() {
    if (!this.background) return;
    for (const item of this.placedFurniture) {
      let sprite = this.furnitureSprites.get(item.id);
      if (!sprite) {
        sprite = this.makeFurniture(item);
        this.furnitureSprites.set(item.id, sprite);
      }
      sprite.setPosition(item.x * this.scale.width, item.y * this.scale.height);
      sprite.setDepth(item.y * 1000);
    }
  }

  makeFurniture(item) {
    const definition = this.furnitureCatalog?.get(item.catalog_id);
    const color = colorNumber(definition?.color);
    const graphics = this.add.graphics();
    graphics.fillStyle(0x385642, 0.16);
    graphics.fillEllipse(0, 15, 44, 13);
    if (definition?.shape === "chair") {
      graphics.fillStyle(color, 1);
      graphics.fillRoundedRect(-15, -16, 30, 20, 7);
      graphics.fillRect(-12, 2, 24, 5);
      graphics.fillRect(-10, 7, 4, 12);
      graphics.fillRect(6, 7, 4, 12);
    } else if (definition?.shape === "table") {
      graphics.fillStyle(color, 1);
      graphics.fillRoundedRect(-25, -5, 50, 15, 7);
      graphics.fillStyle(0x8c6444, 1);
      graphics.fillRect(-16, 8, 5, 10);
      graphics.fillRect(11, 8, 5, 10);
    } else if (definition?.shape === "lamp") {
      graphics.fillStyle(color, 1);
      graphics.fillRoundedRect(-12, -24, 24, 16, 8);
      graphics.fillStyle(0x8c6444, 1);
      graphics.fillRect(-3, -8, 6, 25);
      graphics.fillRoundedRect(-13, 15, 26, 5, 3);
    } else if (definition?.shape === "plant") {
      graphics.fillStyle(0xb87552, 1);
      graphics.fillRoundedRect(-12, 3, 24, 15, 5);
      graphics.fillStyle(color, 1);
      graphics.fillEllipse(-7, -8, 12, 23);
      graphics.fillEllipse(7, -12, 12, 25);
      graphics.fillEllipse(0, -20, 11, 22);
    } else if (definition?.shape === "rug") {
      graphics.fillStyle(color, 1);
      graphics.fillEllipse(0, 5, 62, 24);
      graphics.lineStyle(2, 0xffe6aa, 0.75);
      graphics.strokeEllipse(0, 5, 48, 15);
    } else {
      graphics.fillStyle(color, 1);
      graphics.fillRoundedRect(-13, -5, 26, 14, 6);
      graphics.fillRect(-10, 8, 4, 10);
      graphics.fillRect(6, 8, 4, 10);
    }
    graphics.setInteractive(
      new Phaser.Geom.Rectangle(-32, -30, 64, 54),
      Phaser.Geom.Rectangle.Contains,
    );
    graphics.on("pointerdown", (pointer) => {
      pointer.event.stopPropagation();
      if (this.onDeleteFurniture) this.onDeleteFurniture(item.id);
    });
    graphics.setData("placedFurnitureId", item.id);
    return graphics;
  }

  positionActors() {
    if (this.player) this.placeActor(this.player, this.playerX ?? 0.5, this.playerY ?? 0.68);
    for (const [id, avatar] of this.players) {
      const data = this.roomPlayers?.get(id);
      if (data) this.placeActor(avatar, data.x, data.y);
    }
  }

  placeActor(actor, x, y) {
    actor.setPosition(x * this.scale.width, y * this.scale.height);
    actor.setDepth(y * 1000 + 1);
  }

  setLocalPosition(x, y, emit = true) {
    this.playerX = Math.min(0.94, Math.max(0.06, x));
    this.playerY = Math.min(0.88, Math.max(0.3, y));
    this.placeActor(this.player, this.playerX, this.playerY);
    if (emit) this.onMove?.({ x: this.playerX, y: this.playerY });
  }

  update(_time, delta) {
    if (!this.player) return;
    const left = this.cursors.left.isDown || this.keys.A.isDown;
    const right = this.cursors.right.isDown || this.keys.D.isDown;
    const up = this.cursors.up.isDown || this.keys.W.isDown;
    const down = this.cursors.down.isDown || this.keys.S.isDown;
    const dx = Number(right) - Number(left);
    const dy = Number(down) - Number(up);
    if (dx || dy) {
      const length = Math.hypot(dx, dy) || 1;
      this.destination = null;
      this.setLocalPosition(
        this.playerX + (dx / length) * delta * 0.00022,
        this.playerY + (dy / length) * delta * 0.00022,
      );
    } else if (this.destination) {
      const dxTo = this.destination.x - this.playerX;
      const dyTo = this.destination.y - this.playerY;
      const distance = Math.hypot(dxTo, dyTo);
      if (distance < 0.008) {
        this.destination = null;
      } else {
        this.setLocalPosition(
          this.playerX + (dxTo / distance) * delta * 0.00022,
          this.playerY + (dyTo / distance) * delta * 0.00022,
        );
      }
    }
  }

  onRoomClick(pointer) {
    const normalized = {
      x: pointer.x / this.scale.width,
      y: pointer.y / this.scale.height,
    };
    if (this.activeFurniture) {
      this.onFurniturePlace?.({ ...normalized, catalogId: this.activeFurniture.id });
      this.setFurniture(null);
      return;
    }
    if (normalized.y < 0.3 || normalized.y > 0.89
        || normalized.x < 0.05 || normalized.x > 0.95) return;
    this.destination = normalized;
  }

  setFurniture(item) {
    this.activeFurniture = item || null;
    this.game.canvas.style.cursor = this.activeFurniture ? "crosshair" : "default";
  }

  setCatalog(items) {
    this.furnitureCatalog = new Map(items.map((item) => [item.id, item]));
  }

  setDeleteFurnitureHandler(handler) {
    this.onDeleteFurniture = handler;
  }

  destroy() {
    if (this.resizeHandler) this.scale.off("resize", this.resizeHandler);
  }
}
