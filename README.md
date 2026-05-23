# Cipher

WoW TBC Anniversary addon + Python pipeline that exports character gear, inventory, talent specs, professions, and auction prices into compact per-character briefings you can feed to an AI assistant for gear advice.

## How it works

```
WoW (Cipher addon)
    → SavedVariables/Cipher.lua
        → parse.py       → exports/snapshot_<timestamp>_<char>.json
        → enrich.py      → exports/snapshot_<timestamp>_<char>_enriched.json  (+ Wowhead item data)
        → summarize.py   → exports/briefing_<char>.md
```

The briefing is ~200 lines per character — compact enough to paste directly into any AI chat for gear advice.

## Requirements

- Python 3.8+ (no external dependencies — stdlib only)
- WoW TBC Anniversary (interface 2.5.x)
- **Optional:** [Auctionator](https://www.curseforge.com/wow/addons/auctionator) — provides AH price data for inventory valuation
- **Optional:** [TradeSkillMaster](https://www.tradeskillmaster.com/) + TSM App — provides 14-day dbmarket prices (preferred over Auctionator when available)

## Setup

### 1. Install the addon

Edit `install.sh` and set `ADDONS_DIR` to your WoW AddOns directory:

```bash
# Example paths:
# macOS
ADDONS_DIR="/Applications/World of Warcraft/_anniversary_/Interface/AddOns"

# Windows (Git Bash)
ADDONS_DIR="C:/Program Files (x86)/World of Warcraft/_anniversary_/Interface/AddOns"

# Linux (Steam/Proton)
ADDONS_DIR="$HOME/.local/share/Steam/steamapps/compatdata/<appid>/pfx/drive_c/Program Files (x86)/World of Warcraft/_anniversary_/Interface/AddOns"
```

Then run:

```bash
bash install.sh
```

Or copy the `addon/` folder manually to `<WoW>/_anniversary_/Interface/AddOns/Cipher/`.

### 2. Configure parse.py

Open `parse.py` and update the two path constants near the top to match your system:

```python
WOW_BASE    = Path("/path/to/World of Warcraft/_anniversary_")
WTF_ACCOUNT = WOW_BASE / "WTF/Account/YOUR_ACCOUNT_NAME"
```

Your account name is the folder name inside `WTF/Account/` — usually your BattleTag or login name in uppercase.

## In-game data capture

For each character you want to track:

1. **Log in** — Cipher exports gear, bags, specs, and TSM prices automatically
2. **Open your bank** — visit any bank NPC to capture bank contents
3. **Open each profession** — open each profession frame at least once per session (Enchanting: open the Enchanting frame specifically)
4. **Run an Auctionator scan** (optional) — gives pricing for all items in inventory
5. **Log out cleanly** — SavedVariables flush to disk on logout, not on `/reload`

Type `/cipher` in-game at any time to force a fresh export of the current character.

## Running the pipeline

```bash
cd cipher/
bash export.sh
```

This runs all three steps in order:
1. Parses `SavedVariables/Cipher.lua` → per-character JSON snapshots
2. Prunes old snapshots (keeps only the latest per character)
3. Fetches Wowhead item stats for any new items (cached in `exports/item_cache.json`)
4. Generates `exports/briefing_<char>.md` for each character

You can run steps individually:

```bash
python3 parse.py                          # parse only
python3 enrich.py                         # enrich latest unenriched snapshots
python3 enrich.py exports/snapshot_X.json # enrich a specific snapshot
python3 summarize.py                      # regenerate briefings from enriched snapshots
```

## Output

`exports/briefing_<charname>.md` — a compact character snapshot:

```markdown
# Morphinos — Priest (Human) — Level 70

**Realm:** Thunderstrike (Alliance)
**Exported:** 2026-05-23 07:22 UTC

## Specs
- Spec 1: 14/0/47 (Discipline / Shadow)
- Spec 2 (active): 20/41/0 (Discipline / Holy)

## Gear
[Head] ✦✦✦ Light-Collar of the Incarnate (iLvl 120) | Enchant #3001
  Stats: +28 Stamina, +34 Intellect, +25 Spirit, +72 Healing, +5 MP5
...

## Inventory
### Top items by value
- Large Prismatic Shard x17 [bank] — 324g 30s (19g 07s/TSM each)
...
```

Quality markers: ✦ = Uncommon, ✦✦ = Rare, ✦✦✦ = Epic, ★ = Legendary

## Price data

| Source | Coverage | Notes |
|--------|----------|-------|
| TSM dbmarket | ~8,000–9,000 items | 14-day weighted average; requires TSM App + addon |
| Auctionator | Up to ~30,000 items | Requires a fresh AH scan before logging out |

TSM prices are preferred when both are available.

## Using briefings with an AI

Paste the briefing into any AI chat and ask your question:

> Here's my Holy Priest character data: [paste briefing_morphinos.md]. What epic upgrades should I farm in Karazhan to get ready for SSC/TK?

The briefing is designed to be self-contained — the AI doesn't need any other context to give specific, actionable gear advice.

### Claude Code `/wow` skill

If you use [Claude Code](https://claude.ai/code), a pre-built skill is included at `.claude/commands/wow.md`. After copying it to your user commands directory (`~/.claude/commands/`), type:

```
/wow morphinos gear
/wow angryarchie gold
/wow <charname> professions
```

Claude will read the relevant briefing automatically and answer as a TBC Anniversary expert.

## Repository layout

```
cipher/
├── addon/                  WoW addon
│   ├── Cipher.lua          Main addon logic
│   └── Cipher.toc          Addon manifest
├── exports/                Generated output (gitignored except item_cache.json)
│   └── item_cache.json     Shared Wowhead item stat cache
├── parse.py                SavedVariables → JSON snapshots
├── enrich.py               JSON snapshots → Wowhead-enriched snapshots
├── summarize.py            Enriched snapshots → briefing_<char>.md
├── export.sh               Run full pipeline
└── install.sh              Copy addon to WoW directory
```

## What the addon captures

- Equipped gear: item ID, enchant, gems, and live in-game stats via `GetItemStats()`
- Bags and bank: item ID, name, stack count per slot
- Talent specs (both specs, with tree point distribution)
- Professions (name, current level, max level)
- Auctionator price database (if Auctionator is installed)
- TSM dbmarket prices (if TSM is installed) — queried once per session on `PLAYER_ENTERING_WORLD`
