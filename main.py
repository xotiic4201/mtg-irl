from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
import json, os, uuid
from pathlib import Path
from typing import Optional

app = FastAPI(title="MTG IRL Tracker")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

GAME_MODES = {
    "standard":        {"name": "Standard",          "life": 20, "deck_size": 60,  "commander": False, "commander_dmg_threshold": 21, "poison_threshold": 10, "description": "Current sets only. 60-card decks, 20 life."},
    "historic":        {"name": "Historic",           "life": 20, "deck_size": 60,  "commander": False, "commander_dmg_threshold": 21, "poison_threshold": 10, "description": "Arena format. All Arena-legal cards. 60-card decks."},
    "timeless":        {"name": "Timeless",           "life": 20, "deck_size": 60,  "commander": False, "commander_dmg_threshold": 21, "poison_threshold": 10, "description": "Arena format. No ban list (nearly). Powerful cards legal."},
    "explorer":        {"name": "Explorer",           "life": 20, "deck_size": 60,  "commander": False, "commander_dmg_threshold": 21, "poison_threshold": 10, "description": "Arena's Pioneer equivalent. 60-card decks."},
    "pioneer":         {"name": "Pioneer",            "life": 20, "deck_size": 60,  "commander": False, "commander_dmg_threshold": 21, "poison_threshold": 10, "description": "Post-Khans of Tarkir sets. No Fetch Lands. 60-card decks."},
    "modern":          {"name": "Modern",             "life": 20, "deck_size": 60,  "commander": False, "commander_dmg_threshold": 21, "poison_threshold": 10, "description": "8th Edition and newer. Powerful staples. 60-card decks."},
    "legacy":          {"name": "Legacy",             "life": 20, "deck_size": 60,  "commander": False, "commander_dmg_threshold": 21, "poison_threshold": 10, "description": "Almost all cards legal. Fetch Lands, Duals. 60-card decks."},
    "vintage":         {"name": "Vintage",            "life": 20, "deck_size": 60,  "commander": False, "commander_dmg_threshold": 21, "poison_threshold": 10, "description": "Power Nine legal. Restricted list. 60-card decks."},
    "pauper":          {"name": "Pauper",             "life": 20, "deck_size": 60,  "commander": False, "commander_dmg_threshold": 21, "poison_threshold": 10, "description": "Common cards only. 60-card decks."},
    "commander":       {"name": "Commander / EDH",    "life": 40, "deck_size": 100, "commander": True,  "commander_dmg_threshold": 21, "poison_threshold": 10, "description": "100-card singleton. 40 life. Commander damage at 21."},
    "brawl":           {"name": "Brawl",              "life": 25, "deck_size": 60,  "commander": True,  "commander_dmg_threshold": 21, "poison_threshold": 10, "description": "Standard cards. 60-card singleton. Commander mechanic."},
    "historic_brawl":  {"name": "Historic Brawl",     "life": 25, "deck_size": 100, "commander": True,  "commander_dmg_threshold": 21, "poison_threshold": 10, "description": "Historic-legal cards. 100-card singleton. 25 life."},
    "oathbreaker":     {"name": "Oathbreaker",        "life": 20, "deck_size": 60,  "commander": True,  "commander_dmg_threshold": 21, "poison_threshold": 10, "description": "Planeswalker commander + signature spell. 60-card singleton."},
    "duel_commander":  {"name": "Duel Commander",     "life": 20, "deck_size": 100, "commander": True,  "commander_dmg_threshold": 21, "poison_threshold": 10, "description": "1v1 Commander. 20 life. Stricter ban list."},
    "draft":           {"name": "Draft / Sealed",     "life": 20, "deck_size": 40,  "commander": False, "commander_dmg_threshold": 21, "poison_threshold": 10, "description": "Limited format. 40-card minimum. 20 life."},
    "two_headed_giant":{"name": "Two-Headed Giant",   "life": 30, "deck_size": 60,  "commander": False, "commander_dmg_threshold": 21, "poison_threshold": 15, "description": "2v2 team format. Shared 30 life. 15 poison to lose."},
}

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
    state["activity_log"] = log[:20]


@app.get("/")
def root():
    if Path("index.html").exists():
        return FileResponse("index.html")
    return JSONResponse({"status": "MTG IRL API running"})

@app.get("/modes")
def get_modes():
    return GAME_MODES

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

@app.post("/upload_deck")
async def upload_deck(username: str = Form(...), file: UploadFile = File(...)):
    content = await file.read()
    try:
        deck = json.loads(content)
    except Exception:
        raise HTTPException(400, "Invalid JSON deck file")
    if "cards" not in deck:
        raise HTTPException(400, "Deck must have a 'cards' array")
    state = load_user(username)
    state["deck"] = deck
    log_action(state, f"Deck '{deck.get('name','unnamed')}' uploaded ({len(deck['cards'])} cards)")
    save_user(username, state)
    return {"status": "ok", "card_count": len(deck["cards"]), "deck_name": deck.get("name", "Unnamed Deck")}

@app.post("/load_default_deck")
async def load_default_deck(body: dict):
    username = body.get("username")
    state = load_user(username)
    default_deck = body.get("deck")
    if not default_deck:
        raise HTTPException(400, "No deck provided")
    state["deck"] = default_deck
    log_action(state, f"Default deck '{default_deck.get('name','')}' loaded")
    save_user(username, state)
    return {"status": "ok", "card_count": len(default_deck["cards"])}

@app.get("/get_state/{username}")
def get_state(username: str):
    return load_user(username)

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

@app.post("/add_commander")
async def add_commander(body: dict):
    username = body.get("username")
    card_id = body.get("card_id")
    is_signature_spell = body.get("is_signature_spell", False)
    state = load_user(username)
    deck = state.get("deck")
    if not deck:
        raise HTTPException(400, "No deck loaded")
    card = next((c for c in deck["cards"] if c["id"] == card_id), None)
    if not card:
        raise HTTPException(404, "Card not found")
    zone_key = "signature_spell_zone" if is_signature_spell else "commander_zone"
    entry = {
        "instance_id": str(uuid.uuid4()),
        "card_id": card_id,
        "card_data": card,
        "cast_count": 0,
        "is_signature_spell": is_signature_spell,
    }
    state.setdefault(zone_key, []).append(entry)
    log_action(state, f"{card['name']} set as {'Signature Spell' if is_signature_spell else 'Commander'}")
    save_user(username, state)
    return {zone_key: state[zone_key]}

@app.post("/cast_commander")
async def cast_commander(body: dict):
    username = body.get("username")
    instance_id = body.get("instance_id")
    state = load_user(username)
    cmd_list = state.get("commander_zone", []) + state.get("signature_spell_zone", [])
    cmd = next((c for c in cmd_list if c["instance_id"] == instance_id), None)
    if not cmd:
        raise HTTPException(404, "Commander not found")
    cmd["cast_count"] = cmd.get("cast_count", 0) + 1
    # Recalculate command tax from all commanders
    total_casts = sum(c.get("cast_count", 0) for c in state.get("commander_zone", []))
    state["command_tax"] = total_casts * 2 - 2 if total_casts > 0 else 0
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
    log_action(state, f"Cast commander {cmd['card_data']['name']} (tax: +{state['command_tax']} generic)")
    save_user(username, state)
    return {"battlefield": state["battlefield"], "command_tax": state["command_tax"], "commander_zone": state["commander_zone"]}

@app.post("/return_commander_to_zone")
async def return_commander_to_zone(body: dict):
    username = body.get("username")
    instance_id = body.get("instance_id")
    state = load_user(username)
    card = next((c for c in state["battlefield"] if c["instance_id"] == instance_id), None)
    if not card:
        raise HTTPException(404, "Card not found on battlefield")
    state["battlefield"] = [c for c in state["battlefield"] if c["instance_id"] != instance_id]
    matching = next((c for c in state.get("commander_zone", []) if c["card_id"] == card["card_id"]), None)
    if not matching:
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
    counter_type = body.get("counter_type", "+1/+1")
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
        match = next((c for c in state.get("commander_zone", []) if c["card_id"] == card["card_id"]), None)
        if not match:
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

@app.post("/update_life")
async def update_life(body: dict):
    username = body.get("username")
    delta = body.get("delta", 0)
    state = load_user(username)
    state["life_total"] = state.get("life_total", 20) + delta
    if delta != 0:
        log_action(state, f"Life: {'+' if delta > 0 else ''}{delta} -> {state['life_total']}")
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
    # Preserve deck and commanders, reset everything else
    commanders = []
    for cmd in state.get("commander_zone", []):
        cmd["cast_count"] = 0
        commanders.append(cmd)
    state["battlefield"] = []
    state["graveyard"] = []
    state["exile"] = []
    state["tokens"] = []
    state["hand"] = []
    state["mana_pool"] = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}
    state["life_total"] = m["life"]
    state["commander_damage"] = {}
    state["poison_counters"] = 0
    state["energy_counters"] = 0
    state["storm_count"] = 0
    state["experience_counters"] = 0
    state["rad_counters"] = 0
    state["is_monarch"] = False
    state["has_initiative"] = False
    state["command_tax"] = 0
    state["commander_zone"] = commanders
    state["deck"] = deck
    state["activity_log"] = [f"Game reset ({m['name']})"]
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
                "art_url": "",
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
    removed = len([c for c in state["battlefield"] if c.get("is_token")])
    state["battlefield"] = [c for c in state["battlefield"] if not c.get("is_token")]
    log_action(state, f"Cleared {removed} tokens from battlefield")
    save_user(username, state)
    return {"battlefield": state["battlefield"]}

@app.get("/scan_card/{username}/{card_id}")
def scan_card(username: str, card_id: str):
    state = load_user(username)
    deck = state.get("deck")
    if not deck:
        raise HTTPException(400, "No deck loaded")
    card = next((c for c in deck["cards"] if c["id"] == card_id), None)
    if not card:
        raise HTTPException(404, f"Card ID '{card_id}' not found")
    return card

@app.post("/end_turn")
async def end_turn(body: dict):
    username = body.get("username")
    state = load_user(username)
    order = state.get("player_order", [])
    if not order:
        state["turn_player"] = username
    else:
        current = state.get("turn_player", "")
        try:
            idx = order.index(current)
            next_p = order[(idx + 1) % len(order)]
        except ValueError:
            next_p = order[0]
        state["turn_player"] = next_p
    for c in state["battlefield"]:
        c["tapped"] = False
    state["storm_count"] = 0
    state["mana_pool"] = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}
    log_action(state, f"End of turn. Now: {state['turn_player'] or username}")
    save_user(username, state)
    return {"turn_player": state["turn_player"], "battlefield": state["battlefield"]}

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
    log_action(state, f"Moved {card['card_data']['name']} from graveyard to {destination}")
    save_user(username, state)
    return state

@app.get("/health")
def health():
    return {"status": "ok"}
