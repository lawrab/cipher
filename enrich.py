#!/usr/bin/env python3
"""
enrich.py — fetch item stats from Wowhead and attach them to a snapshot.

Usage:
    python3 enrich.py [snapshot.json]

If no snapshot is given, the most-recent one in exports/ is used.

Item data is cached in exports/item_cache.json so each item ID is only
fetched once. Run again after new snapshots to top up the cache.

Output: prints the snapshot path with a new "items" key added, written to
the same directory as snapshot_<...>_enriched.json
"""

import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

CACHE_FILE = Path(__file__).parent / "exports" / "item_cache.json"
EXPORTS_DIR = Path(__file__).parent / "exports"
WOWHEAD_XML = "https://www.wowhead.com/tbc/item={}&xml"
FETCH_DELAY = 0.5  # seconds between requests, be polite

# Human-readable names for jsonEquip stat keys
STAT_NAMES = {
    "sta":              "Stamina",
    "str":              "Strength",
    "agi":              "Agility",
    "int":              "Intellect",
    "spi":              "Spirit",
    "armor":            "Armor",
    "blockamount":      "Block Value",
    "defrtng":          "Defense Rating",
    "hitrtng":          "Hit Rating",
    "mlehitrtng":       "Hit Rating",
    "rgdhitrtng":       "Hit Rating",
    "critstrkrtng":     "Critical Strike Rating",
    "mlecritstrkrtng":  "Critical Strike Rating",
    "rgdcritstrkrtng":  "Critical Strike Rating",
    "hastrtng":         "Haste Rating",
    "hastertng":        "Haste Rating",
    "exprtng":          "Expertise Rating",
    "atkpwr":           "Attack Power",
    "mleatkpwr":        "Attack Power",
    "rgdatkpwr":        "Ranged Attack Power",
    "parryrtng":        "Parry Rating",
    "dodgertng":        "Dodge Rating",
    "blockrtng":        "Shield Block Rating",
    "mp5":              "Mana per 5 sec",
    "resirtng":         "Resilience Rating",
    "spldmg":           "Spell Damage",
    "splheal":          "Healing",
    "dps":              "DPS",
    "mledps":           "DPS",
    "dmgmin":           "Min Damage",
    "dmgmax":           "Max Damage",
    "mledmgmin":        "Min Damage",
    "mledmgmax":        "Max Damage",
    "speed":            "Weapon Speed",
    "mlespeed":         "Weapon Speed",
    "armorbonus":       "Bonus Armor",
}

# Wowhead quality IDs → names
QUALITY = {0: "Poor", 1: "Common", 2: "Uncommon", 3: "Rare", 4: "Epic", 5: "Legendary"}


def load_cache():
    if CACHE_FILE.exists():
        with open(CACHE_FILE) as f:
            return json.load(f)
    return {}


def save_cache(cache):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


def _cdata(text):
    """Strip CDATA wrapper if present, return plain string."""
    if not text:
        return ""
    return text.strip()


def _extract_tag(raw, tag):
    """Extract text content of first matching XML tag, stripping CDATA."""
    m = re.search(r'<' + tag + r'[^>]*>(.*?)</' + tag + r'>', raw, re.DOTALL)
    if not m:
        return ""
    return m.group(1).replace("<![CDATA[", "").replace("]]>", "").strip()


def _extract_tag_attr(raw, tag, attr):
    """Extract a named attribute from the first matching XML opening tag."""
    m = re.search(r'<' + tag + r'\s+[^>]*' + attr + r'=["\']([^"\']+)["\']', raw)
    return m.group(1) if m else ""


def fetch_item(item_id):
    """
    Fetch item stats from Wowhead XML endpoint.
    Returns a dict with name, level, quality, slot, slotName, and stats.
    Returns None on fetch failure.
    """
    url = WOWHEAD_XML.format(item_id)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  WARN: fetch failed for {item_id}: {e}", file=sys.stderr)
        return None

    # Use regex extraction to avoid ElementTree choking on HTML inside CDATA.
    name      = _extract_tag(raw, "name")
    level_str = _extract_tag(raw, "level")
    slot_name = _extract_tag(raw, "inventorySlot")
    qual_id   = int(_extract_tag_attr(raw, "quality", "id") or 0)
    slot_id   = int(_extract_tag_attr(raw, "inventorySlot", "id") or 0)
    json_str  = _extract_tag(raw, "json")
    equip_str = _extract_tag(raw, "jsonEquip")

    level = int(level_str) if level_str.isdigit() else 0

    req_level = 0
    m = re.search(r'"reqlevel"\s*:\s*(\d+)', json_str or equip_str)
    if m:
        req_level = int(m.group(1))

    # Parse all numeric key:value pairs from jsonEquip
    stats = {}
    if equip_str:
        for m in re.finditer(r'"([^"]+)"\s*:\s*(-?[\d.]+)', equip_str):
            key, val = m.group(1), m.group(2)
            stats[key] = float(val) if "." in val else int(val)

    readable = {STAT_NAMES[k]: v for k, v in stats.items() if k in STAT_NAMES}

    if not name:
        return None

    return {
        "itemID":    item_id,
        "name":      name,
        "ilvl":      level,
        "reqLevel":  req_level,
        "quality":   QUALITY.get(qual_id, str(qual_id)),
        "slotID":    slot_id,
        "slotName":  slot_name,
        "stats":     readable,
        "rawStats":  stats,
    }


def collect_item_ids(snapshot):
    """Return sorted list of all unique item IDs referenced in snapshot."""
    ids = set()
    gear = snapshot.get("gear", {})
    for slot_data in gear.values():
        if isinstance(slot_data, dict):
            iid = slot_data.get("itemID")
            if iid:
                ids.add(int(iid))
            for gem_key in ("gem1", "gem2", "gem3", "gem4"):
                g = slot_data.get(gem_key)
                if g:
                    ids.add(int(g))

    for container_key in ("bags", "bank"):
        container = snapshot.get(container_key, {})
        for bag in container.values():
            if isinstance(bag, dict):
                for slot_data in bag.values():
                    if isinstance(slot_data, dict):
                        iid = slot_data.get("itemID")
                        if iid:
                            ids.add(int(iid))

    ids.discard(0)
    return sorted(ids)


def enrich_snapshot(snapshot_path):
    snapshot_path = Path(snapshot_path)
    with open(snapshot_path) as f:
        snapshot = json.load(f)

    cache = load_cache()
    item_ids = collect_item_ids(snapshot)

    missing = [i for i in item_ids if str(i) not in cache]
    print(f"Snapshot: {snapshot_path.name}")
    print(f"  Total item IDs: {len(item_ids)}  |  Cache hits: {len(item_ids)-len(missing)}  |  To fetch: {len(missing)}")

    for i, item_id in enumerate(missing, 1):
        print(f"  [{i}/{len(missing)}] Fetching item {item_id}...", end=" ", flush=True)
        data = fetch_item(item_id)
        if data:
            cache[str(item_id)] = data
            print(data["name"] or "(no name)")
        else:
            cache[str(item_id)] = None
            print("FAILED")
        if i < len(missing):
            time.sleep(FETCH_DELAY)

    save_cache(cache)

    # Attach item data to snapshot
    snapshot["items"] = {str(k): cache.get(str(k)) for k in item_ids}

    out_path = snapshot_path.parent / snapshot_path.name.replace(".json", "_enriched.json")
    with open(out_path, "w") as f:
        json.dump(snapshot, f, indent=2)
    print(f"  Written: {out_path.name}")
    return out_path


def all_snapshots():
    """Return snapshots that don't yet have an enriched counterpart, newest first."""
    snapshots = sorted(EXPORTS_DIR.glob("snapshot_*.json"), reverse=True)
    snapshots = [s for s in snapshots if "_enriched" not in s.name]
    return [s for s in snapshots if not s.parent.joinpath(s.name.replace(".json", "_enriched.json")).exists()]


if __name__ == "__main__":
    if len(sys.argv) > 1:
        paths = [Path(sys.argv[1])]
    else:
        paths = all_snapshots()
        if not paths:
            print("No snapshots found in exports/", file=sys.stderr)
            sys.exit(1)

    for path in paths:
        enrich_snapshot(path)
        print()
