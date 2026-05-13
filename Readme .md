# MTG IRL Tracker

Real-world Magic: The Gathering game tracker with full game state management.

## Supported Formats

**Arena:** Standard, Historic, Timeless, Explorer
**Paper 60-card:** Pioneer, Modern, Legacy, Vintage, Pauper
**Commander family:** Commander/EDH, Brawl, Historic Brawl, Oathbreaker, Duel Commander
**Limited/Special:** Draft/Sealed, Two-Headed Giant

## Setup

```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 10000
```

Then open http://localhost:10000 in your browser.

## Files

- main.py        — FastAPI backend, 30+ endpoints
- index.html     — Full single-page frontend (inline CSS/JS)
- requirements.txt
- data/          — Auto-created, one JSON file per player

## Deck Format (JSON upload)

```json
{
  "name": "My Deck",
  "cards": [
    {
      "id": "unique_card_id",
      "name": "Card Name",
      "mana_cost": "2RR",
      "type": "Creature - Dragon",
      "text": "Flying, haste",
      "art_url": "https://...",
      "power": 5,
      "toughness": 5
    }
  ]
}
```

Non-creature cards: set `power` and `toughness` to `null`.

## QR Scanning

Set the QR code on each physical card to its `id` field from the deck JSON.
Use the Scan button and enter the scanned ID to look up and add the card.

## Deploy on Render

1. Push all files to a GitHub repo
2. New Web Service on render.com
3. Build command: `pip install -r requirements.txt`
4. Start command: `uvicorn main:app --host 0.0.0.0 --port 10000`
5. Add a persistent disk mounted at `/data`

## Keyboard Shortcuts (card must be selected/clicked first)

- `+` or `=`   Add +1/+1 counter
- `-`           Remove counter
- `T`           Tap / untap
- `Delete`      Remove card (prompts destination)
- `U`           Untap all
- `E`           End turn
