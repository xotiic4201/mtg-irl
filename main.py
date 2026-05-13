from fastapi import FastAPI, UploadFile, File, Form, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
import json, os, uuid, asyncio, re, random
from pathlib import Path
from typing import Dict, List, Optional
import httpx

app = FastAPI(title="MTG IRL Tracker")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

CACHE_FILE = DATA_DIR / "_scryfall_cache.json"
_scryfall_cache: dict = {}

SCRYFALL_BASE = "https://api.scryfall.com"
SCRYFALL_DELAY = 0.1

GAME_MODES = {
    "standard":         {"name": "Standard",         "life": 20,  "deck_size": 60,  "commander": False, "commander_dmg_threshold": 21, "poison_threshold": 10},
    "historic":         {"name": "Historic",          "life": 20,  "deck_size": 60,  "commander": False, "commander_dmg_threshold": 21, "poison_threshold": 10},
    "timeless":         {"name": "Timeless",          "life": 20,  "deck_size": 60,  "commander": False, "commander_dmg_threshold": 21, "poison_threshold": 10},
    "explorer":         {"name": "Explorer",          "life": 20,  "deck_size": 60,  "commander": False, "commander_dmg_threshold": 21, "poison_threshold": 10},
    "pioneer":          {"name": "Pioneer",           "life": 20,  "deck_size": 60,  "commander": False, "commander_dmg_threshold": 21, "poison_threshold": 10},
    "modern":           {"name": "Modern",            "life": 20,  "deck_size": 60,  "commander": False, "commander_dmg_threshold": 21, "poison_threshold": 10},
    "legacy":           {"name": "Legacy",            "life": 20,  "deck_size": 60,  "commander": False, "commander_dmg_threshold": 21, "poison_threshold": 10},
    "vintage":          {"name": "Vintage",           "life": 20,  "deck_size": 60,  "commander": False, "commander_dmg_threshold": 21, "poison_threshold": 10},
    "pauper":           {"name": "Pauper",            "life": 20,  "deck_size": 60,  "commander": False, "commander_dmg_threshold": 21, "poison_threshold": 10},
    "commander":        {"name": "Commander / EDH",   "life": 40,  "deck_size": 100, "commander": True,  "commander_dmg_threshold": 21, "poison_threshold": 10},
    "brawl":            {"name": "Brawl",             "life": 25,  "deck_size": 60,  "commander": True,  "commander_dmg_threshold": 21, "poison_threshold": 10},
    "historic_brawl":   {"name": "Historic Brawl",    "life": 25,  "deck_size": 100, "commander": True,  "commander_dmg_threshold": 21, "poison_threshold": 10},
    "oathbreaker":      {"name": "Oathbreaker",       "life": 20,  "deck_size": 60,  "commander": True,  "commander_dmg_threshold": 21, "poison_threshold": 10},
    "duel_commander":   {"name": "Duel Commander",    "life": 20,  "deck_size": 100, "commander": True,  "commander_dmg_threshold": 21, "poison_threshold": 10},
    "draft":            {"name": "Draft / Sealed",    "life": 20,  "deck_size": 40,  "commander": False, "commander_dmg_threshold": 21, "poison_threshold": 10},
    "two_headed_giant": {"name": "Two-Headed Giant",  "life": 30,  "deck_size": 60,  "commander": False, "commander_dmg_threshold": 21, "poison_threshold": 15},
}

# ── WEBSOCKET ROOM MANAGER ────────────────────────────────────────────────────

class RoomManager:
    def __init__(self):
        # room_id -> { "game": G, "connections": {player_name: websocket} }
        self.rooms: Dict[str, dict] = {}

    def create_room(self, room_id: str, game_state: dict):
        self.rooms[room_id] = {"game": game_state, "connections": {}}

    def room_exists(self, room_id: str) -> bool:
        return room_id in self.rooms

    async def connect(self, room_id: str, player_name: str, ws: WebSocket):
        await ws.accept()
        if room_id not in self.rooms:
            await ws.close(code=4004)
            return False
        self.rooms[room_id]["connections"][player_name] = ws
        await self.broadcast(room_id, {"type": "player_joined", "player": player_name, "game": self.rooms[room_id]["game"]})
        return True

    def disconnect(self, room_id: str, player_name: str):
        if room_id in self.rooms:
            self.rooms[room_id]["connections"].pop(player_name, None)

    async def broadcast(self, room_id: str, message: dict, exclude: str = None):
        if room_id not in self.rooms:
            return
        dead = []
        for name, ws in self.rooms[room_id]["connections"].items():
            if name == exclude:
                continue
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(name)
        for name in dead:
            self.rooms[room_id]["connections"].pop(name, None)

    def update_game(self, room_id: str, game: dict):
        if room_id in self.rooms:
            self.rooms[room_id]["game"] = game

    def get_game(self, room_id: str) -> Optional[dict]:
        return self.rooms.get(room_id, {}).get("game")

    def get_players(self, room_id: str) -> List[str]:
        return list(self.rooms.get(room_id, {}).get("connections", {}).keys())


room_manager = RoomManager()


# ── SCRYFALL CACHE ────────────────────────────────────────────────────────────

def load_scryfall_cache():
    global _scryfall_cache
    if CACHE_FILE.exists():
        try:
            _scryfall_cache = json.loads(CACHE_FILE.read_text())
        except Exception:
            _scryfall_cache = {}

def save_scryfall_cache():
    CACHE_FILE.write_text(json.dumps(_scryfall_cache, indent=2))

load_scryfall_cache()

def _cache_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "_", name.lower().strip())

def _parse_scryfall_card(data: dict, original_id: str = None) -> dict:
    name = data.get("name", "Unknown")
    faces = data.get("card_faces")
    if faces:
        face = faces[0]
        art_url = face.get("image_uris", {}).get("normal") or data.get("image_uris", {}).get("normal", "")
        mana_cost = face.get("mana_cost", data.get("mana_cost", ""))
        type_line = face.get("type_line", data.get("type_line", ""))
        oracle_text = face.get("oracle_text", data.get("oracle_text", ""))
        power = face.get("power", data.get("power"))
        toughness = face.get("toughness", data.get("toughness"))
    else:
        art_url = data.get("image_uris", {}).get("normal", "")
        mana_cost = data.get("mana_cost", "")
        type_line = data.get("type_line", "")
        oracle_text = data.get("oracle_text", "")
        power = data.get("power")
        toughness = data.get("toughness")

    def parse_pt(v):
        if v is None: return None
        try: return int(v)
        except: return str(v)

    card_id = original_id or re.sub(r"[^a-z0-9_]", "_", name.lower())
    keywords = data.get("keywords", [])

    return {
        "id": card_id,
        "name": name,
        "mana_cost": mana_cost.replace("{", "").replace("}", ""),
        "type": type_line,
        "text": oracle_text,
        "art_url": art_url,
        "power": parse_pt(power),
        "toughness": parse_pt(toughness),
        "colors": data.get("colors", []),
        "color_identity": data.get("color_identity", []),
        "cmc": data.get("cmc", 0),
        "rarity": data.get("rarity", ""),
        "set_name": data.get("set_name", ""),
        "scryfall_id": data.get("id", ""),
        "scryfall_uri": data.get("scryfall_uri", ""),
        "legalities": data.get("legalities", {}),
        "keywords": keywords,
        "rulings_uri": data.get("rulings_uri", ""),
    }

async def scryfall_fetch_by_name(name: str, original_id: str = None) -> dict | None:
    key = _cache_key(name)
    if key in _scryfall_cache:
        cached = dict(_scryfall_cache[key])
        if original_id: cached["id"] = original_id
        return cached
    await asyncio.sleep(SCRYFALL_DELAY)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{SCRYFALL_BASE}/cards/named", params={"exact": name}, headers={"User-Agent": "MTG-IRL-Tracker/1.0"})
            if r.status_code == 200:
                card = _parse_scryfall_card(r.json(), original_id)
                _scryfall_cache[key] = card
                save_scryfall_cache()
                return card
            await asyncio.sleep(SCRYFALL_DELAY)
            r2 = await client.get(f"{SCRYFALL_BASE}/cards/named", params={"fuzzy": name}, headers={"User-Agent": "MTG-IRL-Tracker/1.0"})
            if r2.status_code == 200:
                card = _parse_scryfall_card(r2.json(), original_id)
                _scryfall_cache[key] = card
                save_scryfall_cache()
                return card
    except Exception as e:
        print(f"[Scryfall] error for '{name}': {e}")
    return None

async def resolve_deck_cards(cards: list) -> list:
    resolved = []
    for card in cards:
        name = card.get("name", "").strip()
        if not name:
            resolved.append(card)
            continue
        key = _cache_key(name)
        fetched = _scryfall_cache.get(key) or await scryfall_fetch_by_name(name, card.get("id"))
        if fetched:
            merged = dict(fetched)
            merged["id"] = card.get("id") or fetched["id"]
            if card.get("art_url"): merged["art_url"] = card["art_url"]
            resolved.append(merged)
        else:
            resolved.append(card)
    return resolved


# ── MULTIPLAYER SHARED GAME STATE ─────────────────────────────────────────────

def default_shared_game(mode: str, players: list, life_override: int = None) -> dict:
    m = GAME_MODES.get(mode, GAME_MODES["commander"])
    life = life_override or m["life"]
    return {
        "room_id": None,
        "mode": mode,
        "turn": 0,
        "turn_num": 1,
        "phase": "untap",  # untap|upkeep|draw|main1|combat|main2|end|cleanup
        "day_night": None,  # None|day|night
        "stack": [],
        "reminders": [],   # [{id, text, player, phase, expires_turn}]
        "players": [
            {
                "name": p,
                "life": life,
                "counters": {"poison": 0, "energy": 0, "experience": 0, "storm": 0, "rad": 0},
                "cmd_dmg": {},
                "statuses": {"monarch": False, "initiative": False, "day_bound": False, "night_bound": False},
                "cmd_tax": 0,
                "cmd_cast_count": 0,
                "action_log": [],
            }
            for p in players
        ],
        "global_log": [],
        "notes": "",
        "started_at": None,
    }

def log_global(G: dict, msg: str):
    G.setdefault("global_log", []).insert(0, {"turn": G.get("turn_num", 1), "phase": G.get("phase", "?"), "msg": msg})
    G["global_log"] = G["global_log"][:100]

def save_room_game(room_id: str):
    g = room_manager.get_game(room_id)
    if g:
        path = DATA_DIR / f"room_{room_id}.json"
        path.write_text(json.dumps(g, indent=2))

def load_room_game(room_id: str) -> dict | None:
    path = DATA_DIR / f"room_{room_id}.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except:
            pass
    return None


# ── USER STATE (single player) ────────────────────────────────────────────────

def get_user_file(username: str) -> Path:
    safe = "".join(c for c in username if c.isalnum() or c in "-_")
    return DATA_DIR / f"{safe}.json"

def default_state(mode: str = "commander") -> dict:
    m = GAME_MODES.get(mode, GAME_MODES["commander"])
    return {
        "game_mode": mode, "mode_config": m, "deck": None,
        "battlefield": [], "mana_pool": {"W":0,"U":0,"B":0,"R":0,"G":0,"C":0},
        "life_total": m["life"], "commander_damage": {},
        "poison_counters": 0, "energy_counters": 0, "storm_count": 0,
        "experience_counters": 0, "rad_counters": 0,
        "is_monarch": False, "has_initiative": False,
        "turn_player": "", "player_order": [],
        "graveyard": [], "exile": [], "hand": [], "tokens": [],
        "commander_zone": [], "signature_spell_zone": [], "command_tax": 0,
        "activity_log": [],
    }

def load_user(username: str) -> dict:
    f = get_user_file(username)
    if f.exists():
        try: return json.loads(f.read_text())
        except: pass
    return default_state()

def save_user(username: str, state: dict):
    get_user_file(username).write_text(json.dumps(state, indent=2))

def log_action(state: dict, action: str):
    log = state.setdefault("activity_log", [])
    log.insert(0, action)
    state["activity_log"] = log[:25]


# ══════════════════════════════════════════════════════════════════════════════
# ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/")
def root():
    if Path("index.html").exists():
        return FileResponse("index.html")
    return JSONResponse({"status": "MTG IRL API running"})

@app.get("/modes")
def get_modes():
    return GAME_MODES

# ── AUTH ──────────────────────────────────────────────────────────────────────

@app.post("/login")
async def login(body: dict):
    username = body.get("username", "").strip()
    if not username:
        raise HTTPException(400, "Username required")
    state = load_user(username)
    if not state.get("username"):
        state["username"] = username
        save_user(username, state)
    return {
        "status": "ok", "username": username,
        "has_deck": state.get("deck") is not None,
        "game_mode": state.get("game_mode", "commander"),
        "life_total": state.get("life_total", 40),
    }

# ── MULTIPLAYER ROOM MANAGEMENT ───────────────────────────────────────────────

@app.post("/create_room")
async def create_room(body: dict):
    """Create a multiplayer room. Returns a 6-char room code."""
    mode = body.get("mode", "commander")
    players = body.get("players", [])
    life = body.get("life")
    if not players:
        raise HTTPException(400, "Need at least one player")

    room_id = body.get("room_id") or uuid.uuid4().hex[:6].upper()
    G = default_shared_game(mode, players, life)
    G["room_id"] = room_id
    import time
    G["started_at"] = int(time.time())
    room_manager.create_room(room_id, G)
    save_room_game(room_id)
    return {"room_id": room_id, "game": G}

@app.post("/join_room")
async def join_room_http(body: dict):
    """Check if room exists and return its current state."""
    room_id = body.get("room_id", "").strip().upper()
    if not room_id:
        raise HTTPException(400, "Room ID required")
    G = room_manager.get_game(room_id) or load_room_game(room_id)
    if not G:
        raise HTTPException(404, f"Room '{room_id}' not found")
    if not room_manager.room_exists(room_id):
        room_manager.create_room(room_id, G)
    return {"room_id": room_id, "game": G}

@app.post("/room_action")
async def room_action(body: dict):
    """Apply an action to the shared room game and broadcast to all players."""
    room_id = body.get("room_id", "").upper()
    actor = body.get("player", "")
    action = body.get("action", "")
    payload = body.get("payload", {})

    G = room_manager.get_game(room_id)
    if not G:
        G = load_room_game(room_id)
        if not G:
            raise HTTPException(404, "Room not found")
        room_manager.create_room(room_id, G)

    # Find player index
    pidx = next((i for i, p in enumerate(G["players"]) if p["name"] == actor), None)

    if action == "adj_life":
        target = payload.get("target", actor)
        tidx = next((i for i, p in enumerate(G["players"]) if p["name"] == target), pidx)
        if tidx is not None:
            delta = payload.get("delta", 0)
            G["players"][tidx]["life"] += delta
            log_global(G, f"{target}: life {'+'if delta>0 else ''}{delta} → {G['players'][tidx]['life']}")

    elif action == "set_life":
        target = payload.get("target", actor)
        tidx = next((i for i, p in enumerate(G["players"]) if p["name"] == target), pidx)
        if tidx is not None:
            old = G["players"][tidx]["life"]
            G["players"][tidx]["life"] = payload.get("value", old)
            log_global(G, f"{target}: life set to {G['players'][tidx]['life']}")

    elif action == "adj_counter":
        target = payload.get("target", actor)
        tidx = next((i for i, p in enumerate(G["players"]) if p["name"] == target), pidx)
        key = payload.get("key", "poison")
        if tidx is not None:
            p = G["players"][tidx]
            p["counters"][key] = max(0, p["counters"].get(key, 0) + payload.get("delta", 0))

    elif action == "adj_cmd_dmg":
        target = payload.get("target")
        from_player = payload.get("from_player")
        tidx = next((i for i, p in enumerate(G["players"]) if p["name"] == target), None)
        if tidx is not None:
            p = G["players"][tidx]
            cur = p["cmd_dmg"].get(from_player, 0)
            p["cmd_dmg"][from_player] = max(0, cur + payload.get("delta", 0))
            val = p["cmd_dmg"][from_player]
            if val >= 21:
                log_global(G, f"⚠ {target} at {val} commander damage from {from_player}!")

    elif action == "toggle_status":
        target = payload.get("target", actor)
        tidx = next((i for i, p in enumerate(G["players"]) if p["name"] == target), pidx)
        key = payload.get("key")
        if tidx is not None and key:
            G["players"][tidx]["statuses"][key] = not G["players"][tidx]["statuses"].get(key, False)
            state = "on" if G["players"][tidx]["statuses"][key] else "off"
            log_global(G, f"{target}: {key} {state}")

    elif action == "end_turn":
        prev = G["turn"]
        G["turn"] = (G["turn"] + 1) % len(G["players"])
        G["phase"] = "untap"
        if G["turn"] == 0:
            G["turn_num"] += 1
            for p in G["players"]:
                p["counters"]["storm"] = 0
        ap = G["players"][G["turn"]]["name"]
        log_global(G, f"Turn {G['turn_num']}: {ap}'s turn")
        # Expire reminders
        G["reminders"] = [r for r in G.get("reminders", []) if r.get("expires_turn", 9999) > G["turn_num"]]

    elif action == "set_phase":
        G["phase"] = payload.get("phase", G["phase"])
        # Trigger reminder check for this phase
        phase_reminders = [r for r in G.get("reminders", []) if r.get("phase") == G["phase"]]
        if phase_reminders:
            log_global(G, f"⏰ Reminders for {G['phase']}: " + ", ".join(r["text"] for r in phase_reminders))

    elif action == "add_reminder":
        rid = uuid.uuid4().hex[:8]
        reminder = {
            "id": rid,
            "text": payload.get("text", ""),
            "player": actor,
            "phase": payload.get("phase"),
            "expires_turn": payload.get("expires_turn", G["turn_num"] + 999),
            "created_turn": G["turn_num"],
        }
        G.setdefault("reminders", []).append(reminder)
        log_global(G, f"{actor} added reminder: {reminder['text']}")

    elif action == "remove_reminder":
        rid = payload.get("id")
        G["reminders"] = [r for r in G.get("reminders", []) if r["id"] != rid]

    elif action == "push_stack":
        item = {"id": uuid.uuid4().hex[:8], "text": payload.get("text", ""), "player": actor}
        G.setdefault("stack", []).insert(0, item)
        log_global(G, f"Stack: {actor} added '{item['text']}'")

    elif action == "pop_stack":
        if G.get("stack"):
            item = G["stack"].pop(0)
            log_global(G, f"Stack: resolved '{item['text']}'")

    elif action == "clear_stack":
        G["stack"] = []

    elif action == "set_day_night":
        G["day_night"] = payload.get("value")
        log_global(G, f"Day/Night → {G['day_night'] or 'none'}")

    elif action == "update_game":
        # Full state replacement (used for sync)
        incoming = payload.get("game")
        if incoming:
            G = incoming
            G["room_id"] = room_id

    room_manager.update_game(room_id, G)
    save_room_game(room_id)

    await room_manager.broadcast(room_id, {
        "type": "game_update",
        "action": action,
        "actor": actor,
        "game": G,
    })

    return {"game": G}

@app.get("/room/{room_id}")
async def get_room(room_id: str):
    room_id = room_id.upper()
    G = room_manager.get_game(room_id) or load_room_game(room_id)
    if not G:
        raise HTTPException(404, "Room not found")
    players_online = room_manager.get_players(room_id)
    return {"game": G, "players_online": players_online}

# ── WEBSOCKET ─────────────────────────────────────────────────────────────────

@app.websocket("/ws/{room_id}/{player_name}")
async def websocket_endpoint(ws: WebSocket, room_id: str, player_name: str):
    room_id = room_id.upper()
    G = room_manager.get_game(room_id) or load_room_game(room_id)
    if not G:
        # Create room on demand if state exists on disk
        await ws.close(code=4004)
        return
    if not room_manager.room_exists(room_id):
        room_manager.create_room(room_id, G)

    ok = await room_manager.connect(room_id, player_name, ws)
    if not ok:
        return
    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type")
            if msg_type == "ping":
                await ws.send_json({"type": "pong"})
            elif msg_type == "action":
                # Forward to room_action logic inline
                action = data.get("action", "")
                actor = player_name
                payload = data.get("payload", {})
                G_now = room_manager.get_game(room_id)
                if G_now:
                    # Re-use the room_action logic by calling it directly
                    await room_action({"room_id": room_id, "player": actor, "action": action, "payload": payload})
    except WebSocketDisconnect:
        room_manager.disconnect(room_id, player_name)
        await room_manager.broadcast(room_id, {"type": "player_left", "player": player_name})

# ── CARD LOOKUP ───────────────────────────────────────────────────────────────

@app.get("/resolve_card")
async def resolve_card_endpoint(name: str, card_id: str = None):
    card = await scryfall_fetch_by_name(name, card_id)
    if not card:
        raise HTTPException(404, f"Card '{name}' not found")
    return card

@app.get("/search_cards")
async def search_cards(q: str, page: int = 1):
    try:
        await asyncio.sleep(SCRYFALL_DELAY)
        async with httpx.AsyncClient(timeout=12) as client:
            r = await client.get(f"{SCRYFALL_BASE}/cards/search", params={"q": q, "page": page, "order": "name"}, headers={"User-Agent": "MTG-IRL-Tracker/1.0"})
            if r.status_code == 200:
                data = r.json()
                cards = [_parse_scryfall_card(c) for c in data.get("data", [])]
                return {"cards": cards, "total_cards": data.get("total_cards", len(cards)), "has_more": data.get("has_more", False)}
            elif r.status_code == 404:
                return {"cards": [], "total_cards": 0, "has_more": False}
    except Exception as e:
        raise HTTPException(503, str(e))

@app.get("/autocomplete")
async def autocomplete(q: str):
    if len(q) < 2:
        return {"names": []}
    try:
        await asyncio.sleep(SCRYFALL_DELAY)
        async with httpx.AsyncClient(timeout=6) as client:
            r = await client.get(f"{SCRYFALL_BASE}/cards/autocomplete", params={"q": q}, headers={"User-Agent": "MTG-IRL-Tracker/1.0"})
            if r.status_code == 200:
                return {"names": r.json().get("data", [])}
    except Exception:
        pass
    return {"names": []}

@app.get("/card_rulings")
async def card_rulings(scryfall_id: str):
    """Fetch Oracle rulings for a card."""
    try:
        await asyncio.sleep(SCRYFALL_DELAY)
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(f"{SCRYFALL_BASE}/cards/{scryfall_id}/rulings", headers={"User-Agent": "MTG-IRL-Tracker/1.0"})
            if r.status_code == 200:
                rulings = r.json().get("data", [])
                return {"rulings": rulings}
    except Exception as e:
        pass
    return {"rulings": []}

# ── COMPREHENSIVE RULES SEARCH ────────────────────────────────────────────────

RULES_KEYWORDS = {
    "flying": "702.9 — Flying: A creature with flying can't be blocked except by creatures with flying or reach.",
    "deathtouch": "702.2 — Deathtouch: Any amount of damage this creature deals to a creature is enough to destroy it.",
    "hexproof": "702.11 — Hexproof: Can't be the target of spells or abilities your opponents control.",
    "trample": "702.19 — Trample: Excess combat damage may be assigned to the defending player or planeswalker.",
    "lifelink": "702.15 — Lifelink: Damage dealt by this creature also causes you to gain that much life.",
    "vigilance": "702.20 — Vigilance: Attacking doesn't cause this creature to tap.",
    "first strike": "702.7 — First Strike: This creature deals combat damage before creatures without first strike.",
    "double strike": "702.4 — Double Strike: Deals both first-strike and regular combat damage.",
    "menace": "702.111 — Menace: Can only be blocked by two or more creatures.",
    "indestructible": "702.12 — Indestructible: Effects that destroy this permanent have no effect. Lethal damage doesn't destroy it.",
    "flash": "702.8 — Flash: You may cast this spell any time you could cast an instant.",
    "haste": "702.10 — Haste: Can attack and tap the turn it enters the battlefield.",
    "reach": "702.17 — Reach: Can block creatures with flying.",
    "shroud": "702.18 — Shroud: Can't be the target of any spells or abilities.",
    "protection": "702.16 — Protection: Can't be damaged, enchanted, equipped, blocked, or targeted by anything with the specified quality.",
    "ward": "702.20x — Ward: If this creature becomes the target of a spell or ability an opponent controls, counter it unless that player pays the ward cost.",
    "toxic": "702.164 — Toxic N: Deals N poison counters when it deals combat damage to a player (in addition to regular damage).",
    "proliferate": "701.27 — Proliferate: Choose any number of players/permanents with counters; give each another counter of each type they already have.",
    "cascade": "702.84 — Cascade: When you cast this spell, exile cards from the top of your library until you exile a nonland card with lesser MV; cast it for free.",
    "convoke": "702.50 — Convoke: Each creature you tap while casting this spell pays 1 or one mana of that creature's color.",
    "storm": "702.39 — Storm: When you cast this spell, copy it for each other spell cast this turn.",
    "annihilator": "702.86 — Annihilator N: Whenever this creature attacks, defending player sacrifices N permanents.",
    "infect": "702.90 — Infect: Deals damage to players as poison counters and to creatures as -1/-1 counters.",
    "wither": "702.79 — Wither: Deals damage to creatures in the form of -1/-1 counters.",
    "flanking": "702.25 — Flanking: When blocked by a creature without flanking, that creature gets -1/-1 until EOT.",
    "partner": "702.124 — Partner: Can have two commanders if both have partner.",
    "commander tax": "Rule 903.8 — Commander Tax: Each time you cast your commander from the command zone, it costs 2 more for each previous time you've cast it.",
    "state based actions": "704 — State-Based Actions: Checked continuously; include life ≤0 (lose), 0 toughness (dies), 10+ poison (loses), legend rule, etc.",
    "priority": "116 — Priority: Active player gets priority first each step/phase. Players may cast spells or activate abilities when they have priority.",
    "the stack": "112, 405 — The Stack: Where spells and abilities wait to resolve. Resolves last-in, first-out (LIFO).",
    "mana burn": "Removed in Magic 2010. Unspent mana no longer causes damage.",
    "layers": "613 — Layers: The system for applying continuous effects in order: copy → control → text → type → color → ability → power/toughness.",
    "replacement effects": "614 — Replacement Effects: Modify how events happen (e.g., damage redirected, counters doubled). They don't use the stack.",
    "trigger": "603 — Triggered Abilities: Begin with 'when', 'whenever', or 'at'. They trigger, go on the stack, and can be responded to.",
    "enters the battlefield": "ETB — Enters-the-Battlefield: When a permanent comes into play. Replacement effects apply before it 'exists' on the battlefield.",
    "commander damage": "903.10 — Commander Damage: A player who has been dealt 21 or more combat damage by a single commander loses the game.",
    "monarch": "The Monarch: The monarch draws an extra card at the beginning of their end step. You become the monarch by dealing combat damage to the current monarch.",
    "initiative": "The Initiative: The player with the initiative ventures into Undercity at the beginning of their upkeep.",
    "day": "Day/Night — Daybound: If it's night, transforms to its night face. If no spells were cast on the active player's last turn, it becomes night.",
}

@app.get("/rules_search")
async def rules_search(q: str):
    q_lower = q.lower().strip()
    results = []
    for keyword, text in RULES_KEYWORDS.items():
        if q_lower in keyword or keyword in q_lower:
            results.append({"keyword": keyword, "rule": text})
    if not results:
        # Fuzzy fallback
        for keyword, text in RULES_KEYWORDS.items():
            words = q_lower.split()
            if any(w in keyword for w in words if len(w) > 2):
                results.append({"keyword": keyword, "rule": text})
    return {"results": results[:10], "query": q}

# ── DICE ──────────────────────────────────────────────────────────────────────

@app.get("/roll")
async def roll_dice(sides: int = 6, count: int = 1):
    count = min(count, 10)
    sides = max(2, min(sides, 1000))
    rolls = [random.randint(1, sides) for _ in range(count)]
    return {"rolls": rolls, "total": sum(rolls), "sides": sides}

@app.get("/coin_flip")
async def coin_flip(count: int = 1):
    count = min(count, 10)
    flips = [random.choice(["Heads", "Tails"]) for _ in range(count)]
    return {"flips": flips}

@app.post("/random_player")
async def random_player(body: dict):
    players = body.get("players", [])
    if not players:
        raise HTTPException(400, "No players")
    return {"player": random.choice(players)}

# ── SINGLE-PLAYER ROUTES (legacy) ────────────────────────────────────────────

@app.post("/set_mode")
async def set_mode(body: dict):
    username = body.get("username")
    mode = body.get("mode", "commander")
    if mode not in GAME_MODES:
        raise HTTPException(400, f"Unknown mode: {mode}")
    state = load_user(username)
    m = GAME_MODES[mode]
    state["game_mode"] = mode
    state["mode_config"] = m
    save_user(username, state)
    return {"status": "ok", "game_mode": mode, "mode_config": m}

@app.post("/upload_deck")
async def upload_deck(username: str = Form(...), file: UploadFile = File(...)):
    content = await file.read()
    try:
        deck = json.loads(content)
    except Exception:
        raise HTTPException(400, "Invalid JSON deck file")
    if "cards" not in deck or not isinstance(deck["cards"], list):
        raise HTTPException(400, "Deck must have a 'cards' array")
    deck["cards"] = await resolve_deck_cards(deck["cards"])
    state = load_user(username)
    state["deck"] = deck
    save_user(username, state)
    return {"status": "ok", "card_count": len(deck["cards"])}

@app.get("/resolve_card")
async def resolve_card_ep(name: str, card_id: str = None):
    card = await scryfall_fetch_by_name(name, card_id)
    if not card:
        raise HTTPException(404, f"Card '{name}' not found")
    return card

@app.get("/health")
async def health():
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            r = await client.get(f"{SCRYFALL_BASE}/cards/named", params={"exact": "Plains"}, headers={"User-Agent": "MTG-IRL-Tracker/1.0"})
            scryfall_ok = r.status_code == 200
    except Exception:
        scryfall_ok = False
    return {"status": "ok", "scryfall": "reachable" if scryfall_ok else "unreachable", "cache_size": len(_scryfall_cache), "rooms": len(room_manager.rooms)}
