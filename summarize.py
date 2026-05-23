#!/usr/bin/env python3
"""
summarize.py — generate a compact BRIEFING.md from an enriched snapshot.

Usage:
    python3 summarize.py [snapshot_enriched.json]

If no file given, processes the latest enriched snapshot for each character.
Output: exports/briefing_<char>.md
"""

import json
import sys
from pathlib import Path
from collections import defaultdict

EXPORTS_DIR = Path(__file__).parent / "exports"

SLOT_NAMES = {
    "1": "Head", "2": "Neck", "3": "Shoulder", "4": "Shirt",
    "5": "Chest", "6": "Waist", "7": "Legs", "8": "Feet",
    "9": "Wrist", "10": "Hands", "11": "Ring 1", "12": "Ring 2",
    "13": "Trinket 1", "14": "Trinket 2", "15": "Back",
    "16": "Main Hand", "17": "Off Hand", "18": "Ranged", "19": "Tabard",
}

QUALITY_COLOUR = {
    "Poor": "", "Common": "", "Uncommon": "✦", "Rare": "✦✦", "Epic": "✦✦✦", "Legendary": "★",
}


def copper_to_gold(copper):
    if not isinstance(copper, int) or copper <= 0:
        return None
    g = copper // 10000
    s = (copper % 10000) // 100
    c = copper % 100
    if g:
        return f"{g}g {s:02d}s"
    if s:
        return f"{s}s {c:02d}c"
    return f"{c}c"


def best_price(item_id, tsm, auc):
    """Return (price_str, source) preferring TSM dbmarket."""
    sid = str(item_id)
    t = tsm.get(sid, {})
    if t.get("dbmarket_gold"):
        return t["dbmarket_gold"], "TSM"
    a = auc.get(sid, {})
    if a.get("gold"):
        return a["gold"], "AH"
    return None, None


def format_stats(stats):
    if not stats:
        return ""
    priority = [
        "Stamina", "Strength", "Agility", "Intellect", "Spirit",
        "Attack Power", "DPS",
        "Hit Rating", "Expertise Rating", "Critical Strike Rating", "Haste Rating",
        "Defense Rating", "Dodge Rating", "Parry Rating", "Shield Block Rating", "Block Value",
        "Armor", "Bonus Armor",
        "Spell Damage", "Healing", "Spell Power", "Mana per 5 sec",
        "Ranged Attack Power", "Spell Hit Rating", "Spell Crit Rating",
        "Resilience Rating", "Armor Penetration",
        "Fire Resistance", "Nature Resistance", "Frost Resistance",
        "Shadow Resistance", "Arcane Resistance", "Holy Resistance",
    ]
    ordered = []
    seen = set()
    for k in priority:
        if k in stats and k not in seen:
            ordered.append((k, stats[k]))
            seen.add(k)
    for k, v in stats.items():
        if k not in seen:
            ordered.append((k, v))
    parts = []
    for k, v in ordered:
        # Skip resistances with 0 value (shouldn't happen after translate, but guard anyway)
        if isinstance(v, (int, float)) and v == 0:
            continue
        short = (k.replace("Critical Strike Rating", "Crit")
                   .replace(" Rating", "")
                   .replace("Attack Power", "AP")
                   .replace("Mana per 5 sec", "MP5"))
        prefix = "" if k == "DPS" else "+"
        parts.append(f"{prefix}{int(v)} {short}")
    return ", ".join(parts)


def spec_label(spec):
    trees = spec.get("trees", [])
    pts = "/".join(str(t.get("pointsSpent", 0)) for t in trees)
    names = " / ".join(t.get("tree", "?") for t in trees if t.get("pointsSpent", 0) > 0)
    return f"{pts} ({names})"


def summarize(snapshot_path):
    snapshot_path = Path(snapshot_path)
    with open(snapshot_path) as f:
        snap = json.load(f)

    meta        = snap.get("meta", {})
    gear        = snap.get("gear", {})
    bags        = snap.get("bags", {})
    bank        = snap.get("bank", {})
    talents     = snap.get("talents", [])
    professions = snap.get("professions", [])
    prices      = snap.get("prices", {})
    tsm         = snap.get("tsmPrices", {})
    items_db    = snap.get("items", {})

    char   = meta.get("character", "Unknown")
    lines  = []
    add    = lines.append

    # ── Header ──────────────────────────────────────────────────
    add(f"# {char} — {meta.get('class', '?').title()} ({meta.get('race', '?').title()}) — Level {meta.get('level', '?')}")
    add("")
    add(f"**Realm:** {meta.get('realm', '?')} ({meta.get('faction', '?')})")
    add(f"**Exported:** {meta.get('exportedAt', '?')}")
    if meta.get("bankUpdatedAt"):
        add(f"**Bank updated:** {meta.get('bankUpdatedAt')}")
    if meta.get("priceUpdatedAt"):
        add(f"**AH prices:** {meta.get('priceCount', 0):,} items as of {meta.get('priceUpdatedAt')}")
    add("")

    # ── Specs ────────────────────────────────────────────────────
    add("## Specs")
    if talents:
        for i, spec in enumerate(talents, 1):
            active = " **(active)**" if spec.get("active") else ""
            add(f"- Spec {i}{active}: {spec_label(spec)}")
    else:
        add("- No talent data")
    add("")

    # ── Professions ──────────────────────────────────────────────
    add("## Professions")
    if professions:
        for p in professions:
            add(f"- {p['name']} {p['level']}/{p['maxLevel']}")
    else:
        add("- No profession data (open a profession window in-game)")
    add("")

    # ── Gear ─────────────────────────────────────────────────────
    add("## Gear")
    add("")
    for slot_num in range(1, 20):
        slot = str(slot_num)
        item = gear.get(slot)
        if not item:
            continue
        slot_name = SLOT_NAMES.get(slot, f"Slot {slot}")
        item_id   = item.get("itemID", 0)
        item_name = item.get("name") or f"Item {item_id}"

        # Stats: prefer in-game GetItemStats, fall back to Wowhead
        stats = item.get("stats")
        if not stats and item_id:
            wowhead = items_db.get(str(item_id), {}) or {}
            stats = wowhead.get("stats")

        wowhead    = items_db.get(str(item_id), {}) or {}
        ilvl       = wowhead.get("ilvl", "?")
        quality    = wowhead.get("quality", "")
        qual_mark  = QUALITY_COLOUR.get(quality, "")

        enchant_id = item.get("enchantID", 0)
        gems       = [item.get(f"gem{i}") for i in range(1, 5) if item.get(f"gem{i}")]

        parts = [f"**[{slot_name}]** {qual_mark} {item_name}"]
        if ilvl and ilvl != "?":
            parts[0] += f" (iLvl {ilvl})"
        if enchant_id:
            parts[0] += f" | Enchant #{enchant_id}"
        if gems:
            gem_names = []
            for gid in gems:
                g = items_db.get(str(gid), {}) or {}
                gem_names.append(g.get("name") or f"Gem#{gid}")
            parts[0] += f" | Gems: {', '.join(gem_names)}"
        add(parts[0])
        if stats:
            add(f"  Stats: {format_stats(stats)}")
    add("")

    # ── Inventory (bags + bank) ───────────────────────────────────
    all_items = []  # (name, item_id, count, location)
    for bag_id, bag in bags.items():
        for slot_id, entry in bag.items():
            iid   = entry.get("itemID", 0)
            name  = entry.get("name") or f"Item {iid}"
            count = entry.get("count", 1)
            all_items.append((name, iid, count, "bag"))
    for bag_id, bag in bank.items():
        for slot_id, entry in bag.items():
            iid   = entry.get("itemID", 0)
            name  = entry.get("name") or f"Item {iid}"
            count = entry.get("count", 1)
            all_items.append((name, iid, count, "bank"))

    # Consolidate stacks
    consolidated = defaultdict(lambda: {"count": 0, "item_id": 0, "locations": set()})
    for name, iid, count, loc in all_items:
        consolidated[name]["count"]    += count
        consolidated[name]["item_id"]   = iid
        consolidated[name]["locations"].add(loc)

    # Compute value and sort by total TSM/AH value descending
    valued = []
    for name, info in consolidated.items():
        iid   = info["item_id"]
        count = info["count"]
        price_str, source = best_price(iid, tsm, prices)
        total_copper = None
        t = tsm.get(str(iid), {})
        a = prices.get(str(iid), {})
        unit_copper = t.get("dbmarket") or a.get("copper")
        if unit_copper:
            total_copper = unit_copper * count
        valued.append((name, iid, count, info["locations"], price_str, source, total_copper))

    valued.sort(key=lambda x: x[6] or 0, reverse=True)

    add("## Inventory")
    add("")

    if valued:
        add("### Top items by value")
        for name, iid, count, locs, price_str, source, total_copper in valued[:30]:
            loc_tag = "+".join(sorted(locs))
            total_str = copper_to_gold(total_copper) if total_copper else "—"
            unit_str  = f" ({price_str}/{source} each)" if price_str else ""
            stack_str = f" x{count}" if count > 1 else ""
            add(f"- {name}{stack_str} [{loc_tag}] — {total_str}{unit_str}")
        add("")

        add("### All inventory")
        for name, iid, count, locs, price_str, source, total_copper in valued:
            loc_tag   = "+".join(sorted(locs))
            total_str = copper_to_gold(total_copper) if total_copper else "—"
            unit_str  = f" ({price_str}/{source} each)" if price_str else ""
            stack_str = f" x{count}" if count > 1 else ""
            add(f"- {name}{stack_str} [{loc_tag}] — {total_str}{unit_str}")
    else:
        add("No inventory data.")
    add("")

    # ── Price reference ───────────────────────────────────────────
    add("## Price data")
    add("")
    add(f"Full Auctionator prices: {len(prices):,} items — query by item ID from `prices` key in snapshot.")
    add(f"TSM market prices: {len(tsm):,} items — use `tsmPrices` key (dbmarket = 14-day average).")
    add("")
    add(f"Full enriched snapshot: `{snapshot_path.name}`")

    briefing_name = f"briefing_{char.lower()}.md"
    out_path = EXPORTS_DIR / briefing_name
    with open(out_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"  Written: {briefing_name}")
    return out_path


def all_enriched():
    return sorted(EXPORTS_DIR.glob("snapshot_*_enriched.json"), reverse=True)


def latest_enriched_per_char():
    seen = {}
    for f in sorted(EXPORTS_DIR.glob("snapshot_*_enriched.json"), reverse=True):
        # e.g. snapshot_20260523_082345_angryarchie_enriched.json
        char = f.stem.replace("_enriched", "").rsplit("_", 1)[-1]
        if char not in seen:
            seen[char] = f
    return list(seen.values())


if __name__ == "__main__":
    if len(sys.argv) > 1:
        paths = [Path(sys.argv[1])]
    else:
        paths = latest_enriched_per_char()
        if not paths:
            print("No enriched snapshots found. Run export.sh first.")
            sys.exit(1)

    for path in paths:
        print(f"Summarising {path.name}...")
        summarize(path)
