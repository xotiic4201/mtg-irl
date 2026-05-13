from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
import json, os, uuid, asyncio, re
from pathlib import Path
import httpx

app = FastAPI(title="MTG IRL Tracker")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

CACHE_FILE = DATA_DIR / "_scryfall_cache.json"
_scryfall_cache: dict = {}

SCRYFALL_BASE = "https://api.scryfall.com"
SCRYFALL_DELAY = 0.1  # Scryfall requests 100ms between calls

GAME_MODES = {
    "standard":         {"name": "Standard",         "life": 20,  "deck_size": 60,  "commander": False, "commander_dmg_threshold": 21, "poison_threshold": 10,  "description": "Current sets only. 60-card decks, 20 life."},
    "historic":         {"name": "Historic",          "life": 20,  "deck_size": 60,  "commander": False, "commander_dmg_threshold": 21, "poison_threshold": 10,  "description": "Arena format. All Arena-legal cards. 60-card decks."},
    "timeless":         {"name": "Timeless",          "life": 20,  "deck_size": 60,  "commander": False, "commander_dmg_threshold": 21, "poison_threshold": 10,  "description": "Arena format. Near-unrestricted. 60-card decks."},
    "explorer":         {"name": "Explorer",          "life": 20,  "deck_size": 60,  "commander": False, "commander_dmg_threshold": 21, "poison_threshold": 10,  "description": "Arena Pioneer equivalent. 60-card decks."},
    "pioneer":          {"name": "Pioneer",           "life": 20,  "deck_size": 60,  "commander": False, "commander_dmg_threshold": 21, "poison_threshold": 10,  "description": "Post-Khans. No Fetch Lands. 60-card decks."},
    "modern":           {"name": "Modern",            "life": 20,  "deck_size": 60,  "commander": False, "commander_dmg_threshold": 21, "poison_threshold": 10,  "description": "8th Edition and newer. 60-card decks."},
    "legacy":           {"name": "Legacy",            "life": 20,  "deck_size": 60,  "commander": False, "commander_dmg_threshold": 21, "poison_threshold": 10,  "description": "Duals and Fetches legal. 60-card decks."},
    "vintage":          {"name": "Vintage",           "life": 20,  "deck_size": 60,  "commander": False, "commander_dmg_threshold": 21, "poison_threshold": 10,  "description": "Power Nine legal. Restricted list."},
    "pauper":           {"name": "Pauper",            "life": 20,  "deck_size": 60,  "commander": False, "commander_dmg_threshold": 21, "poison_threshold": 10,  "description": "Common cards only. 60-card decks."},
    "commander":        {"name": "Commander / EDH",   "life": 40,  "deck_size": 100, "commander": True,  "commander_dmg_threshold": 21, "poison_threshold": 10,  "description": "100-card singleton. 40 life. Commander damage at 21."},
    "brawl":            {"name": "Brawl",             "life": 25,  "deck_size": 60,  "commander": True,  "commander_dmg_threshold": 21, "poison_threshold": 10,  "description": "Standard singleton. 25 life. Commander mechanic."},
    "historic_brawl":   {"name": "Historic Brawl",    "life": 25,  "deck_size": 100, "commander": True,  "commander_dmg_threshold": 21, "poison_threshold": 10,  "description": "Historic singleton. 100 cards. 25 life."},
    "oathbreaker":      {"name": "Oathbreaker",       "life": 20,  "deck_size": 60,  "commander": True,  "commander_dmg_threshold": 21, "poison_threshold": 10,  "description": "Planeswalker commander + signature spell."},
    "duel_commander":   {"name": "Duel Commander",    "life": 20,  "deck_size": 100, "commander": True,  "commander_dmg_threshold": 21, "poison_threshold": 10,  "description": "1v1 Commander. 20 life. Strict ban list."},
    "draft":            {"name": "Draft / Sealed",    "life": 20,  "deck_size": 40,  "commander": False, "commander_dmg_threshold": 21, "poison_threshold": 10,  "description": "Limited format. 40-card minimum. 20 life."},
    "two_headed_giant": {"name": "Two-Headed Giant",  "life": 30,  "deck_size": 60,  "commander": False, "commander_dmg_threshold": 21, "poison_threshold": 15,  "description": "2v2 team format. Shared 30 life. 15 poison to lose."},
}


# ── SCRYFALL CACHE ─────────────────────────────────────────────────────────────

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
    """Convert Scryfall API response into our card format."""
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
        if v is None:
            return None
        try:
            return int(v)
        except (ValueError, TypeError):
            return str(v)

    card_id = original_id or re.sub(r"[^a-z0-9_]", "_", name.lower())

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
    }


async def scryfall_fetch_by_name(name: str, original_id: str = None) -> dict | None:
    """Fetch a card from Scryfall by exact name. Falls back to fuzzy. Uses disk cache."""
    key = _cache_key(name)
    if key in _scryfall_cache:
        cached = dict(_scryfall_cache[key])
        if original_id:
            cached["id"] = original_id
        return cached

    await asyncio.sleep(SCRYFALL_DELAY)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{SCRYFALL_BASE}/cards/named",
                params={"exact": name},
                headers={"User-Agent": "MTG-IRL-Tracker/1.0"},
            )
            if r.status_code == 200:
                card = _parse_scryfall_card(r.json(), original_id)
                _scryfall_cache[key] = card
                save_scryfall_cache()
                return card
            # exact miss — try fuzzy
            await asyncio.sleep(SCRYFALL_DELAY)
            r2 = await client.get(
                f"{SCRYFALL_BASE}/cards/named",
                params={"fuzzy": name},
                headers={"User-Agent": "MTG-IRL-Tracker/1.0"},
            )
            if r2.status_code == 200:
                card = _parse_scryfall_card(r2.json(), original_id)
                _scryfall_cache[key] = card
                save_scryfall_cache()
                return card
    except Exception as e:
        print(f"[Scryfall] fetch error for '{name}': {e}")
    return None


async def resolve_deck_cards(cards: list) -> list:
    """
    For every card in the deck:
    - If art_url is missing, fetch full data from Scryfall
    - If art_url exists but metadata is thin, enrich it
    - Cards with user-supplied art_url keep their art
    Always respects Scryfall rate limit (100ms between requests).
    """
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
            # Keep user-supplied art if they provided it
            if card.get("art_url"):
                merged["art_url"] = card["art_url"]
            # Keep user-supplied text overrides
            if card.get("text") and card["text"] != fetched.get("text", ""):
                merged["text"] = card["text"]
            resolved.append(merged)
        else:
            resolved.append(card)

    return resolved


# ── USER STATE ─────────────────────────────────────────────────────────────────

def get_user_file(username: str) -> Path:
    safe = "".join(c for c in username if c.isalnum() or c in "-_")
    return DATA_DIR / f"{safe}.json"


def default_state(mode: str = "commander") -> dict:
    m = GAME_MODES.get(mode, GAME_MODES["commander"])
    return {
        "game_mode": mode,
        "mode_config": m,
        "deck": None,
        "battlefield": [],
        "mana_pool": {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0},
        "life_total": m["life"],
        "commander_damage": {},
        "poison_counters": 0,
        "energy_counters": 0,
        "storm_count": 0,
        "experience_counters": 0,
        "rad_counters": 0,
        "is_monarch": False,
        "has_initiative": False,
        "turn_player": "",
        "player_order": [],
        "graveyard": [],
        "exile": [],
        "hand": [],
        "tokens": [],
        "commander_zone": [],
        "signature_spell_zone": [],
        "command_tax": 0,
        "activity_log": [],
    }


def load_user(username: str) -> dict:
    f = get_user_file(username)
    if f.exists():
        try:
            return json.loads(f.read_text())
        except Exception:
            pass
    return default_state()


def save_user(username: str, state: dict):
    get_user_file(username).write_text(json.dumps(state, indent=2))


def log_action(state: dict, action: str):
    log = state.setdefault("activity_log", [])
    log.insert(0, action)
    state["activity_log"] = log[:25]


# ── ROUTES ─────────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    if Path("index.html").exists():
        return FileResponse("index.html")
    return JSONResponse({"status": "MTG IRL API running"})


@app.get("/modes")
def get_modes():
    return GAME_MODES


# ── AUTH ───────────────────────────────────────────────────────────────────────

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
        "status": "ok",
        "username": username,
        "has_deck": state.get("deck") is not None,
        "game_mode": state.get("game_mode", "commander"),
        "life_total": state.get("life_total", 40),
    }


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
    log_action(state, f"Format set to {m['name']}")
    save_user(username, state)
    return {"status": "ok", "game_mode": mode, "mode_config": m}


# ── DECK ───────────────────────────────────────────────────────────────────────

@app.post("/upload_deck")
async def upload_deck(username: str = Form(...), file: UploadFile = File(...)):
    content = await file.read()
    try:
        deck = json.loads(content)
    except Exception:
        raise HTTPException(400, "Invalid JSON deck file")
    if "cards" not in deck or not isinstance(deck["cards"], list):
        raise HTTPException(400, "Deck must have a 'cards' array")

    # Auto-fetch art and metadata for every card
    deck["cards"] = await resolve_deck_cards(deck["cards"])

    state = load_user(username)
    state["deck"] = deck
    resolved = sum(1 for c in deck["cards"] if c.get("art_url"))
    log_action(state, f"Deck '{deck.get('name','unnamed')}' loaded — {resolved}/{len(deck['cards'])} cards resolved")
    save_user(username, state)
    return {
        "status": "ok",
        "card_count": len(deck["cards"]),
        "deck_name": deck.get("name", "Unnamed Deck"),
        "resolved": resolved,
    }


@app.post("/load_default_deck")
async def load_default_deck(body: dict):
    username = body.get("username")
    deck = body.get("deck")
    if not deck:
        raise HTTPException(400, "No deck provided")

    # Auto-fetch art for starter deck cards
    deck["cards"] = await resolve_deck_cards(deck["cards"])

    state = load_user(username)
    state["deck"] = deck
    resolved = sum(1 for c in deck["cards"] if c.get("art_url"))
    log_action(state, f"Deck '{deck.get('name','')}' loaded — {resolved}/{len(deck['cards'])} cards resolved")
    save_user(username, state)
    return {"status": "ok", "card_count": len(deck["cards"]), "resolved": resolved}


@app.post("/resolve_deck")
async def resolve_deck_endpoint(body: dict):
    """Re-resolve all cards in the loaded deck. Use if Scryfall was down on upload."""
    username = body.get("username")
    state = load_user(username)
    if not state.get("deck"):
        raise HTTPException(400, "No deck loaded")
    state["deck"]["cards"] = await resolve_deck_cards(state["deck"]["cards"])
    resolved = sum(1 for c in state["deck"]["cards"] if c.get("art_url"))
    log_action(state, f"Deck re-resolved — {resolved}/{len(state['deck']['cards'])} cards")
    save_user(username, state)
    return {"status": "ok", "card_count": len(state["deck"]["cards"]), "resolved": resolved}


@app.get("/resolve_card")
async def resolve_card_endpoint(name: str, card_id: str = None):
    """Look up any card by name and return full Scryfall data including art URL."""
    card = await scryfall_fetch_by_name(name, card_id)
    if not card:
        raise HTTPException(404, f"Card '{name}' not found on Scryfall")
    return card


@app.get("/search_cards")
async def search_cards(q: str, page: int = 1):
    """Full Scryfall card search. Supports any Scryfall search syntax."""
    try:
        await asyncio.sleep(SCRYFALL_DELAY)
        async with httpx.AsyncClient(timeout=12) as client:
            r = await client.get(
                f"{SCRYFALL_BASE}/cards/search",
                params={"q": q, "page": page, "order": "name"},
                headers={"User-Agent": "MTG-IRL-Tracker/1.0"},
            )
            if r.status_code == 200:
                data = r.json()
                cards = [_parse_scryfall_card(c) for c in data.get("data", [])]
                return {
                    "cards": cards,
                    "total_cards": data.get("total_cards", len(cards)),
                    "has_more": data.get("has_more", False),
                    "next_page": page + 1 if data.get("has_more") else None,
                }
            elif r.status_code == 404:
                return {"cards": [], "total_cards": 0, "has_more": False}
            else:
                raise HTTPException(r.status_code, "Scryfall search error")
    except httpx.RequestError as e:
        raise HTTPException(503, f"Scryfall unreachable: {e}")


@app.get("/autocomplete")
async def autocomplete(q: str):
    """Card name autocomplete powered by Scryfall. Returns up to 20 suggestions."""
    if len(q) < 2:
        return {"names": []}
    try:
        await asyncio.sleep(SCRYFALL_DELAY)
        async with httpx.AsyncClient(timeout=6) as client:
            r = await client.get(
                f"{SCRYFALL_BASE}/cards/autocomplete",
                params={"q": q},
                headers={"User-Agent": "MTG-IRL-Tracker/1.0"},
            )
            if r.status_code == 200:
                return {"names": r.json().get("data", [])}
    except Exception:
        pass
    return {"names": []}


# ── STATE ──────────────────────────────────────────────────────────────────────

@app.get("/get_state/{username}")
def get_state(username: str):
    return load_user(username)


# ── BATTLEFIELD ────────────────────────────────────────────────────────────────

@app.post("/add_to_battlefield")
async def add_to_battlefield(body: dict):
    username = body.get("username")
    card_id = body.get("card_id")
    state = load_user(username)
    deck = state.get("deck")
    if not deck:
        raise HTTPException(400, "No deck loaded")

    card = next((c for c in deck["cards"] if c["id"] == card_id), None)
    if not card:
        raise HTTPException(404, f"Card '{card_id}' not found in deck")

    # Live-resolve art if still missing
    if not card.get("art_url"):
        fetched = await scryfall_fetch_by_name(card["name"], card_id)
        if fetched:
            idx = next(i for i, c in enumerate(deck["cards"]) if c["id"] == card_id)
            merged = {**fetched, "id": card_id}
            deck["cards"][idx] = merged
            card = merged
            state["deck"] = deck

    instance = {
        "instance_id": str(uuid.uuid4()),
        "card_id": card_id,
        "card_data": card,
        "counters": 0,
        "tapped": False,
        "is_token": False,
        "is_commander": False,
        "marked_damage": 0,
        "notes": "",
    }
    state["battlefield"].append(instance)
    log_action(state, f"Added {card['name']} to battlefield")
    save_user(username, state)
    return {"battlefield": state["battlefield"]}


@app.post("/add_card_by_name")
async def add_card_by_name(body: dict):
    """Add any card to the battlefield by name — fetches from Scryfall automatically."""
    username = body.get("username")
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(400, "Card name required")

    state = load_user(username)
    card = await scryfall_fetch_by_name(name)
    if not card:
        raise HTTPException(404, f"Card '{name}' not found on Scryfall")

    # Add to deck catalogue if not already there
    deck = state.get("deck") or {"name": "Ad-hoc", "cards": []}
    if not any(c["name"].lower() == name.lower() for c in deck["cards"]):
        deck["cards"].append(card)
    state["deck"] = deck

    instance = {
        "instance_id": str(uuid.uuid4()),
        "card_id": card["id"],
        "card_data": card,
        "counters": 0,
        "tapped": False,
        "is_token": False,
        "is_commander": False,
        "marked_damage": 0,
        "notes": "",
    }
    state["battlefield"].append(instance)
    log_action(state, f"Added {card['name']} to battlefield (searched by name)")
    save_user(username, state)
    return {"battlefield": state["battlefield"], "card": card}


@app.post("/add_commander")
async def add_commander(body: dict):
    username = body.get("username")
    card_id = body.get("card_id")
    is_signature_spell = body.get("is_signature_spell", False)
    state = load_user(username)
    deck = state.get("deck")

    card = None
    if deck:
        card = next((c for c in deck["cards"] if c["id"] == card_id), None)
    if not card:
        card = await scryfall_fetch_by_name(card_id.replace("_", " "))
    if not card:
        raise HTTPException(404, "Card not found")

    zone_key = "signature_spell_zone" if is_signature_spell else "commander_zone"
    state[zone_key] = [c for c in state.get(zone_key, []) if c["card_id"] != card_id]
    state.setdefault(zone_key, []).append({
        "instance_id": str(uuid.uuid4()),
        "card_id": card_id,
        "card_data": card,
        "cast_count": 0,
        "is_signature_spell": is_signature_spell,
    })
    log_action(state, f"{card['name']} set as {'Signature Spell' if is_signature_spell else 'Commander'}")
    save_user(username, state)
    return {zone_key: state[zone_key]}


@app.post("/cast_commander")
async def cast_commander(body: dict):
    username = body.get("username")
    instance_id = body.get("instance_id")
    state = load_user(username)
    all_cmds = state.get("commander_zone", []) + state.get("signature_spell_zone", [])
    cmd = next((c for c in all_cmds if c["instance_id"] == instance_id), None)
    if not cmd:
        raise HTTPException(404, "Commander not found")
    cmd["cast_count"] = cmd.get("cast_count", 0) + 1
    total_casts = sum(c.get("cast_count", 0) for c in state.get("commander_zone", []))
    state["command_tax"] = max(0, (total_casts - 1) * 2)
    instance = {
        "instance_id": str(uuid.uuid4()),
        "card_id": cmd["card_id"],
        "card_data": cmd["card_data"],
        "counters": 0,
        "tapped": False,
        "is_token": False,
        "is_commander": True,
        "marked_damage": 0,
        "notes": "",
    }
    state["battlefield"].append(instance)
    log_action(state, f"Cast {cmd['card_data']['name']} (command tax: +{state['command_tax']})")
    save_user(username, state)
    return {
        "battlefield": state["battlefield"],
        "command_tax": state["command_tax"],
        "commander_zone": state["commander_zone"],
    }


@app.post("/return_commander_to_zone")
async def return_commander_to_zone(body: dict):
    username = body.get("username")
    instance_id = body.get("instance_id")
    state = load_user(username)
    card = next((c for c in state["battlefield"] if c["instance_id"] == instance_id), None)
    if not card:
        raise HTTPException(404, "Card not found on battlefield")
    state["battlefield"] = [c for c in state["battlefield"] if c["instance_id"] != instance_id]
    exists = any(c["card_id"] == card["card_id"] for c in state.get("commander_zone", []))
    if not exists:
        state.setdefault("commander_zone", []).append({
            "instance_id": str(uuid.uuid4()),
            "card_id": card["card_id"],
            "card_data": card["card_data"],
            "cast_count": 0,
        })
    log_action(state, f"Returned {card['card_data']['name']} to Command Zone")
    save_user(username, state)
    return {"battlefield": state["battlefield"], "commander_zone": state["commander_zone"]}


@app.post("/update_counter")
async def update_counter(body: dict):
    username = body.get("username")
    instance_id = body.get("instance_id")
    delta = body.get("delta", 0)
    state = load_user(username)
    card = next((c for c in state["battlefield"] if c["instance_id"] == instance_id), None)
    if not card:
        raise HTTPException(404, "Card instance not found")
    card["counters"] = max(0, card.get("counters", 0) + delta)
    save_user(username, state)
    return {"instance_id": instance_id, "counters": card["counters"]}


@app.post("/toggle_tap")
async def toggle_tap(body: dict):
    username = body.get("username")
    instance_id = body.get("instance_id")
    state = load_user(username)
    card = next((c for c in state["battlefield"] if c["instance_id"] == instance_id), None)
    if not card:
        raise HTTPException(404, "Card instance not found")
    card["tapped"] = not card.get("tapped", False)
    save_user(username, state)
    return {"instance_id": instance_id, "tapped": card["tapped"]}


@app.post("/remove_card")
async def remove_card(body: dict):
    username = body.get("username")
    instance_id = body.get("instance_id")
    destination = body.get("destination", "graveyard")
    state = load_user(username)
    card = next((c for c in state["battlefield"] if c["instance_id"] == instance_id), None)
    if not card:
        raise HTTPException(404, "Card instance not found")
    state["battlefield"] = [c for c in state["battlefield"] if c["instance_id"] != instance_id]
    dest_label = destination
    if destination == "exile":
        state.setdefault("exile", []).append(card)
    elif destination == "hand":
        state.setdefault("hand", []).append(card)
    elif destination == "commander_zone":
        exists = any(c["card_id"] == card["card_id"] for c in state.get("commander_zone", []))
        if not exists:
            state.setdefault("commander_zone", []).append({
                "instance_id": str(uuid.uuid4()),
                "card_id": card["card_id"],
                "card_data": card["card_data"],
                "cast_count": 0,
            })
        dest_label = "Command Zone"
    else:
        state.setdefault("graveyard", []).append(card)
    log_action(state, f"Moved {card['card_data']['name']} to {dest_label}")
    save_user(username, state)
    return {"battlefield": state["battlefield"], "destination": destination}


# ── MANA ───────────────────────────────────────────────────────────────────────

@app.post("/update_mana")
async def update_mana(body: dict):
    username = body.get("username")
    color = body.get("color")
    delta = body.get("delta", 0)
    state = load_user(username)
    if color not in state["mana_pool"]:
        raise HTTPException(400, "Invalid mana color")
    state["mana_pool"][color] = max(0, state["mana_pool"][color] + delta)
    save_user(username, state)
    return {"mana_pool": state["mana_pool"]}


@app.post("/clear_mana")
async def clear_mana(body: dict):
    username = body.get("username")
    state = load_user(username)
    state["mana_pool"] = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}
    save_user(username, state)
    return {"mana_pool": state["mana_pool"]}


# ── LIFE ───────────────────────────────────────────────────────────────────────

@app.post("/update_life")
async def update_life(body: dict):
    username = body.get("username")
    delta = body.get("delta", 0)
    state = load_user(username)
    state["life_total"] = state.get("life_total", 20) + delta
    if delta != 0:
        log_action(state, f"Life: {'+' if delta > 0 else ''}{delta} = {state['life_total']}")
    save_user(username, state)
    return {"life_total": state["life_total"]}


@app.post("/set_life")
async def set_life(body: dict):
    username = body.get("username")
    value = body.get("value")
    state = load_user(username)
    old = state.get("life_total", 20)
    state["life_total"] = value
    log_action(state, f"Life set to {value} (was {old})")
    save_user(username, state)
    return {"life_total": state["life_total"]}


# ── COUNTERS ───────────────────────────────────────────────────────────────────

@app.post("/update_commander_damage")
async def update_commander_damage(body: dict):
    username = body.get("username")
    opponent = body.get("opponent")
    delta = body.get("delta", 0)
    state = load_user(username)
    cur = state["commander_damage"].get(opponent, 0)
    state["commander_damage"][opponent] = max(0, cur + delta)
    new_val = state["commander_damage"][opponent]
    threshold = state.get("mode_config", {}).get("commander_dmg_threshold", 21)
    if new_val >= threshold:
        log_action(state, f"LETHAL: {new_val} commander damage from {opponent}!")
    save_user(username, state)
    return {"commander_damage": state["commander_damage"]}


@app.post("/update_poison")
async def update_poison(body: dict):
    username = body.get("username")
    delta = body.get("delta", 0)
    state = load_user(username)
    state["poison_counters"] = max(0, state.get("poison_counters", 0) + delta)
    threshold = state.get("mode_config", {}).get("poison_threshold", 10)
    if state["poison_counters"] >= threshold:
        log_action(state, f"LETHAL: {state['poison_counters']} poison counters!")
    save_user(username, state)
    return {"poison_counters": state["poison_counters"]}


@app.post("/update_energy")
async def update_energy(body: dict):
    username = body.get("username")
    delta = body.get("delta", 0)
    state = load_user(username)
    state["energy_counters"] = max(0, state.get("energy_counters", 0) + delta)
    save_user(username, state)
    return {"energy_counters": state["energy_counters"]}


@app.post("/update_storm")
async def update_storm(body: dict):
    username = body.get("username")
    delta = body.get("delta", 0)
    state = load_user(username)
    state["storm_count"] = max(0, state.get("storm_count", 0) + delta)
    save_user(username, state)
    return {"storm_count": state["storm_count"]}


@app.post("/update_experience")
async def update_experience(body: dict):
    username = body.get("username")
    delta = body.get("delta", 0)
    state = load_user(username)
    state["experience_counters"] = max(0, state.get("experience_counters", 0) + delta)
    save_user(username, state)
    return {"experience_counters": state["experience_counters"]}


@app.post("/update_rad")
async def update_rad(body: dict):
    username = body.get("username")
    delta = body.get("delta", 0)
    state = load_user(username)
    state["rad_counters"] = max(0, state.get("rad_counters", 0) + delta)
    save_user(username, state)
    return {"rad_counters": state["rad_counters"]}


# ── STATUS ─────────────────────────────────────────────────────────────────────

@app.post("/toggle_monarch")
async def toggle_monarch(body: dict):
    username = body.get("username")
    state = load_user(username)
    state["is_monarch"] = not state.get("is_monarch", False)
    log_action(state, f"{'Became' if state['is_monarch'] else 'Lost'} the Monarch")
    save_user(username, state)
    return {"is_monarch": state["is_monarch"]}


@app.post("/toggle_initiative")
async def toggle_initiative(body: dict):
    username = body.get("username")
    state = load_user(username)
    state["has_initiative"] = not state.get("has_initiative", False)
    log_action(state, f"{'Took' if state['has_initiative'] else 'Lost'} the Initiative")
    save_user(username, state)
    return {"has_initiative": state["has_initiative"]}


# ── GAME FLOW ──────────────────────────────────────────────────────────────────

@app.post("/reset_game")
async def reset_game(body: dict):
    username = body.get("username")
    mode = body.get("mode")
    state = load_user(username)
    deck = state.get("deck")
    if mode and mode in GAME_MODES:
        state["game_mode"] = mode
        state["mode_config"] = GAME_MODES[mode]
    m = GAME_MODES.get(state.get("game_mode", "commander"), GAME_MODES["commander"])
    commanders = []
    for cmd in state.get("commander_zone", []):
        cmd["cast_count"] = 0
        commanders.append(cmd)
    state.update({
        "battlefield": [],
        "graveyard": [],
        "exile": [],
        "tokens": [],
        "hand": [],
        "mana_pool": {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0},
        "life_total": m["life"],
        "commander_damage": {},
        "poison_counters": 0,
        "energy_counters": 0,
        "storm_count": 0,
        "experience_counters": 0,
        "rad_counters": 0,
        "is_monarch": False,
        "has_initiative": False,
        "command_tax": 0,
        "commander_zone": commanders,
        "deck": deck,
        "activity_log": [f"Game reset — {m['name']} ({m['life']} starting life)"],
    })
    save_user(username, state)
    return state


@app.post("/untap_all")
async def untap_all(body: dict):
    username = body.get("username")
    state = load_user(username)
    for c in state["battlefield"]:
        c["tapped"] = False
    save_user(username, state)
    return {"battlefield": state["battlefield"]}


@app.post("/tap_all")
async def tap_all(body: dict):
    username = body.get("username")
    state = load_user(username)
    for c in state["battlefield"]:
        c["tapped"] = True
    save_user(username, state)
    return {"battlefield": state["battlefield"]}


@app.post("/end_turn")
async def end_turn(body: dict):
    username = body.get("username")
    state = load_user(username)
    order = state.get("player_order", [])
    if order:
        current = state.get("turn_player", "")
        try:
            idx = order.index(current)
            state["turn_player"] = order[(idx + 1) % len(order)]
        except ValueError:
            state["turn_player"] = order[0]
    else:
        state["turn_player"] = username
    for c in state["battlefield"]:
        c["tapped"] = False
    state["storm_count"] = 0
    state["mana_pool"] = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}
    log_action(state, f"End of turn. Now: {state['turn_player']}")
    save_user(username, state)
    return {"turn_player": state["turn_player"], "battlefield": state["battlefield"]}


# ── TOKENS ─────────────────────────────────────────────────────────────────────

@app.post("/create_token")
async def create_token(body: dict):
    username = body.get("username")
    name = body.get("name", "Token")
    power = body.get("power", 1)
    toughness = body.get("toughness", 1)
    color = body.get("color", "")
    token_type = body.get("token_type", "Token Creature")
    text = body.get("text", "")
    count = max(1, min(body.get("count", 1), 50))

    # Auto-fetch token art from Scryfall
    art_url = ""
    try:
        await asyncio.sleep(SCRYFALL_DELAY)
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(
                f"{SCRYFALL_BASE}/cards/search",
                params={"q": f'type:token name:"{name}"', "order": "released"},
                headers={"User-Agent": "MTG-IRL-Tracker/1.0"},
            )
            if r.status_code == 200:
                results = r.json().get("data", [])
                if results:
                    art_url = results[0].get("image_uris", {}).get("normal", "")
    except Exception:
        pass

    state = load_user(username)
    created = []
    for _ in range(count):
        tid = uuid.uuid4().hex[:8]
        token = {
            "instance_id": str(uuid.uuid4()),
            "card_id": f"token_{tid}",
            "card_data": {
                "id": f"token_{tid}",
                "name": name,
                "mana_cost": "0",
                "type": token_type,
                "text": text,
                "art_url": art_url,
                "power": power,
                "toughness": toughness,
                "color": color,
            },
            "counters": 0,
            "tapped": False,
            "is_token": True,
            "is_commander": False,
            "marked_damage": 0,
            "notes": "",
        }
        state["battlefield"].append(token)
        created.append(token)
    log_action(state, f"Created {count}x {power}/{toughness} {name} token{'s' if count > 1 else ''}")
    save_user(username, state)
    return {"battlefield": state["battlefield"], "created": len(created)}


@app.delete("/clear_tokens")
async def clear_tokens(body: dict):
    username = body.get("username")
    state = load_user(username)
    removed = sum(1 for c in state["battlefield"] if c.get("is_token"))
    state["battlefield"] = [c for c in state["battlefield"] if not c.get("is_token")]
    log_action(state, f"Cleared {removed} token{'s' if removed != 1 else ''} from battlefield")
    save_user(username, state)
    return {"battlefield": state["battlefield"]}


# ── SCAN ───────────────────────────────────────────────────────────────────────

@app.get("/scan_card/{username}/{card_id}")
async def scan_card(username: str, card_id: str):
    state = load_user(username)
    deck = state.get("deck")

    # Check deck first
    if deck:
        card = next((c for c in deck["cards"] if c["id"] == card_id), None)
        if card:
            if not card.get("art_url"):
                fetched = await scryfall_fetch_by_name(card["name"], card_id)
                if fetched:
                    idx = next(i for i, c in enumerate(deck["cards"]) if c["id"] == card_id)
                    deck["cards"][idx] = {**fetched, "id": card_id}
                    state["deck"] = deck
                    save_user(username, state)
                    return deck["cards"][idx]
            return card

    # Not in deck — try Scryfall directly (card_id may be a name slug or UUID)
    card = await scryfall_fetch_by_name(card_id.replace("_", " "))
    if card:
        return card

    raise HTTPException(404, f"Card '{card_id}' not found in deck or on Scryfall")


# ── ZONES ──────────────────────────────────────────────────────────────────────

@app.post("/move_from_graveyard")
async def move_from_graveyard(body: dict):
    username = body.get("username")
    instance_id = body.get("instance_id")
    destination = body.get("destination", "battlefield")
    state = load_user(username)
    card = next((c for c in state.get("graveyard", []) if c["instance_id"] == instance_id), None)
    if not card:
        raise HTTPException(404, "Card not found in graveyard")
    state["graveyard"] = [c for c in state["graveyard"] if c["instance_id"] != instance_id]
    if destination == "battlefield":
        card["tapped"] = False
        state["battlefield"].append(card)
        log_action(state, f"Reanimated {card['card_data']['name']}")
    elif destination == "exile":
        state.setdefault("exile", []).append(card)
        log_action(state, f"Exiled {card['card_data']['name']} from graveyard")
    elif destination == "hand":
        state.setdefault("hand", []).append(card)
        log_action(state, f"Returned {card['card_data']['name']} to hand from graveyard")
    save_user(username, state)
    return state


@app.post("/update_card_notes")
async def update_card_notes(body: dict):
    username = body.get("username")
    instance_id = body.get("instance_id")
    notes = body.get("notes", "")
    state = load_user(username)
    card = next((c for c in state["battlefield"] if c["instance_id"] == instance_id), None)
    if not card:
        raise HTTPException(404, "Card not found")
    card["notes"] = notes[:200]
    save_user(username, state)
    return {"instance_id": instance_id, "notes": card["notes"]}


# ── HEALTH ─────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            r = await client.get(
                f"{SCRYFALL_BASE}/cards/named",
                params={"exact": "Plains"},
                headers={"User-Agent": "MTG-IRL-Tracker/1.0"},
            )
            scryfall_ok = r.status_code == 200
    except Exception:
        scryfall_ok = False
    return {
        "status": "ok",
        "scryfall": "reachable" if scryfall_ok else "unreachable",
        "cache_size": len(_scryfall_cache),
    }
