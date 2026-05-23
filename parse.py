#!/usr/bin/env python3
"""
parse.py — Cipher snapshot parser
Reads CipherDB and CipherCharDB SavedVariables, outputs JSON snapshots to exports/.
Usage: python3 parse.py [--char CharName]
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# ============================================================
# Paths
# ============================================================

WOW_BASE = Path.home() / ".local/share/Steam/steamapps/compatdata/3579333542/pfx/drive_c/Program Files (x86)/World of Warcraft/_anniversary_"
WTF_ACCOUNT = WOW_BASE / "WTF/Account/LRABBETS"
ACCOUNT_SV  = WTF_ACCOUNT / "SavedVariables/Cipher.lua"
EXPORTS_DIR = Path(__file__).parent / "exports"

# ============================================================
# Lua parser
# ============================================================

class LuaParser:
    """Minimal recursive-descent parser for WoW SavedVariables Lua format."""

    def __init__(self, text):
        self.text   = text
        self.pos    = 0
        self.length = len(text)

    def _skip(self):
        """Skip whitespace and line comments."""
        while self.pos < self.length:
            c = self.text[self.pos]
            if c in ' \t\n\r':
                self.pos += 1
            elif self.text[self.pos:self.pos + 2] == '--':
                while self.pos < self.length and self.text[self.pos] != '\n':
                    self.pos += 1
            else:
                break

    def _peek(self):
        self._skip()
        return self.text[self.pos] if self.pos < self.length else None

    def _parse_string(self):
        assert self.text[self.pos] == '"', f"Expected '\"' at {self.pos}"
        self.pos += 1
        result = []
        while self.pos < self.length:
            c = self.text[self.pos]
            if c == '\\':
                self.pos += 1
                if self.pos >= self.length:
                    break
                esc = self.text[self.pos]
                self.pos += 1
                if   esc == 'n':  result.append('\n')
                elif esc == 't':  result.append('\t')
                elif esc == 'r':  result.append('\r')
                elif esc == '\\': result.append('\\')
                elif esc == '"':  result.append('"')
                elif esc.isdigit():
                    # Decimal escape \ddd (up to 3 digits)
                    num = esc
                    for _ in range(2):
                        if self.pos < self.length and self.text[self.pos].isdigit():
                            num += self.text[self.pos]
                            self.pos += 1
                    try:
                        result.append(chr(int(num)))
                    except (ValueError, OverflowError):
                        result.append('?')
                else:
                    result.append(esc)
            elif c == '"':
                self.pos += 1
                break
            else:
                result.append(c)
                self.pos += 1
        return ''.join(result)

    def _parse_number(self):
        start = self.pos
        if self.pos < self.length and self.text[self.pos] == '-':
            self.pos += 1
        while self.pos < self.length and (self.text[self.pos].isdigit() or self.text[self.pos] == '.'):
            self.pos += 1
        s = self.text[start:self.pos]
        try:
            return float(s) if '.' in s else int(s)
        except ValueError:
            return 0

    def _parse_value(self):
        self._skip()
        if self.pos >= self.length:
            return None
        c = self.text[self.pos]
        if c == '{':
            return self._parse_table()
        elif c == '"':
            return self._parse_string()
        elif self.text[self.pos:self.pos + 4] == 'true':
            self.pos += 4
            return True
        elif self.text[self.pos:self.pos + 5] == 'false':
            self.pos += 5
            return False
        elif self.text[self.pos:self.pos + 3] == 'nil':
            self.pos += 3
            return None
        elif c == '-' or c.isdigit():
            return self._parse_number()
        return None

    def _parse_table(self):
        assert self.text[self.pos] == '{', f"Expected '{{' at {self.pos}"
        self.pos += 1
        result      = {}
        array_index = 1

        while True:
            self._skip()
            if self.pos >= self.length:
                break
            c = self.text[self.pos]

            if c == '}':
                self.pos += 1
                break
            elif c == ',':
                self.pos += 1
                continue
            elif c == '[':
                self.pos += 1  # skip '['
                self._skip()
                if self.pos < self.length and self.text[self.pos] == '"':
                    key = self._parse_string()
                else:
                    key = self._parse_number()
                self._skip()
                if self.pos < self.length and self.text[self.pos] == ']':
                    self.pos += 1
                self._skip()
                if self.pos < self.length and self.text[self.pos] == '=':
                    self.pos += 1
                value          = self._parse_value()
                result[key]    = value
            else:
                # Bare identifier key (e.g. version = 1)
                m = re.match(r'([A-Za-z_][A-Za-z0-9_]*)\s*=', self.text[self.pos:])
                if m:
                    key         = m.group(1)
                    self.pos   += m.end()
                    value       = self._parse_value()
                    result[key] = value
                else:
                    # Positional array element — track whether _parse_value() consumed any chars
                    # so we can correctly handle nil holes (Lua arrays can have nil at any index)
                    pos_before = self.pos
                    value = self._parse_value()
                    consumed = self.pos > pos_before
                    if value is not None:
                        result[array_index] = value
                        array_index += 1
                    elif consumed:
                        # nil literal — preserve the index gap so subsequent slots stay correct
                        array_index += 1
                    else:
                        self.pos += 1  # truly unknown token, skip to avoid infinite loop

        return result

    def parse_globals(self):
        """Parse all top-level  VAR = value  assignments."""
        result = {}
        while True:
            self._skip()
            if self.pos >= self.length:
                break
            m = re.match(r'([A-Za-z_][A-Za-z0-9_]*)\s*=\s*', self.text[self.pos:])
            if m:
                name        = m.group(1)
                self.pos   += m.end()
                result[name] = self._parse_value()
            else:
                self.pos += 1
        return result


def parse_lua_file(path):
    try:
        with open(path, 'rb') as f:
            raw = f.read()
        # WoW writes SavedVariables with Windows line endings
        text = raw.decode('utf-8', errors='replace').replace('\r\n', '\n')
        return LuaParser(text).parse_globals()
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"  Warning: failed to parse {path}: {e}", file=sys.stderr)
        return {}


# ============================================================
# Item link decoder
# ============================================================

# TBC item link format:
#   |cffQQQQQQ|Hitem:itemID:enchantID:gem1:gem2:gem3:gem4:suffixID:uniqueID|h[Name]|h|r
LINK_RE = re.compile(
    r'\|c[0-9a-fA-F]{8}\|Hitem:([^|]+)\|h\[([^\]]*)\]\|h\|r'
)

def decode_link(link):
    if not link or not isinstance(link, str):
        return None
    m = LINK_RE.match(link)
    if not m:
        return {"raw": link}
    parts = m.group(1).split(':')
    name  = m.group(2)
    def _int(i):
        try: return int(parts[i]) if i < len(parts) else 0
        except ValueError: return 0
    return {
        "name":      name,
        "itemID":    _int(0),
        "enchantID": _int(1),
        "gem1":      _int(2),
        "gem2":      _int(3),
        "gem3":      _int(4),
        "gem4":      _int(5),
        "suffixID":  _int(6),
        "uniqueID":  _int(7),
    }


# ============================================================
# Copper → readable gold string
# ============================================================

def copper_to_gold(copper):
    if not isinstance(copper, int):
        return str(copper)
    g = copper // 10000
    s = (copper % 10000) // 100
    c = copper % 100
    return f"{g}g {s:02d}s {c:02d}c"


# ============================================================
# ITEM_MOD_* → human-readable stat names (from GetItemStats API)
# ============================================================

ITEM_MOD_MAP = {
    # Primary stats — TBC Anniversary returns these as plain English already,
    # but keep _SHORT variants for completeness
    "ITEM_MOD_STAMINA_SHORT":               "Stamina",
    "ITEM_MOD_STRENGTH_SHORT":              "Strength",
    "ITEM_MOD_AGILITY_SHORT":               "Agility",
    "ITEM_MOD_INTELLECT_SHORT":             "Intellect",
    "ITEM_MOD_SPIRIT_SHORT":                "Spirit",
    # Secondary/rating stats — TBC Anniversary returns WITHOUT _SHORT suffix
    "ITEM_MOD_HIT_RATING":                  "Hit Rating",
    "ITEM_MOD_CRIT_RATING":                 "Critical Strike Rating",
    "ITEM_MOD_HASTE_RATING":                "Haste Rating",
    "ITEM_MOD_EXPERTISE_RATING":            "Expertise Rating",
    "ITEM_MOD_DEFENSE_SKILL_RATING":        "Defense Rating",
    "ITEM_MOD_DODGE_RATING":                "Dodge Rating",
    "ITEM_MOD_PARRY_RATING":                "Parry Rating",
    "ITEM_MOD_BLOCK_RATING":                "Shield Block Rating",
    "ITEM_MOD_BLOCK_VALUE":                 "Block Value",
    "ITEM_MOD_RESILIENCE_RATING":           "Resilience Rating",
    "ITEM_MOD_SPELL_DAMAGE_DONE":           "Spell Damage",
    "ITEM_MOD_SPELL_HEALING_DONE":          "Healing",
    "ITEM_MOD_SPELL_POWER":                 "Spell Power",
    # A few secondary stats DO use _SHORT in TBC Anniversary
    "ITEM_MOD_DAMAGE_PER_SECOND_SHORT":     "DPS",
    "ITEM_MOD_MELEE_ATTACK_POWER_SHORT":    "Attack Power",
    "ITEM_MOD_POWER_REGEN0_SHORT":          "Mana per 5 sec",
    # _SHORT variants kept as fallback
    "ITEM_MOD_HIT_RATING_SHORT":            "Hit Rating",
    "ITEM_MOD_CRIT_RATING_SHORT":           "Critical Strike Rating",
    "ITEM_MOD_EXPERTISE_RATING_SHORT":      "Expertise Rating",
    "ITEM_MOD_DEFENSE_SKILL_RATING_SHORT":  "Defense Rating",
    "ITEM_MOD_DODGE_RATING_SHORT":          "Dodge Rating",
    "ITEM_MOD_PARRY_RATING_SHORT":          "Parry Rating",
    "ITEM_MOD_BLOCK_RATING_SHORT":          "Shield Block Rating",
    "ITEM_MOD_ATTACK_POWER_SHORT":          "Attack Power",
    "ITEM_MOD_RANGED_ATTACK_POWER_SHORT":   "Ranged Attack Power",
    "ITEM_MOD_FERAL_ATTACK_POWER_SHORT":    "Feral Attack Power",
    "ITEM_MOD_ARMOR_PENETRATION_RATING_SHORT": "Armor Penetration",
    "ITEM_MOD_SPELL_DAMAGE_DONE_SHORT":     "Spell Damage",
    "ITEM_MOD_SPELL_HEALING_DONE_SHORT":    "Healing",
    # Additional spell stats returned without _SHORT in TBC Anniversary
    "ITEM_MOD_CRIT_SPELL_RATING":           "Spell Crit Rating",
    "ITEM_MOD_HIT_SPELL_RATING":            "Spell Hit Rating",
    "ITEM_MOD_SPELL_PENETRATION":           "Spell Penetration",
    # Armor and elemental resistances
    "RESISTANCE0_NAME":                     "Armor",
    "RESISTANCE1_NAME":                     "Holy Resistance",
    "RESISTANCE2_NAME":                     "Fire Resistance",
    "RESISTANCE3_NAME":                     "Nature Resistance",
    "RESISTANCE4_NAME":                     "Frost Resistance",
    "RESISTANCE5_NAME":                     "Shadow Resistance",
    "RESISTANCE6_NAME":                     "Arcane Resistance",
}

# Empty socket keys returned by GetItemStats — not actual stats, skip them
_EMPTY_SOCKET_KEYS = {
    "EMPTY_SOCKET_BLUE", "EMPTY_SOCKET_RED", "EMPTY_SOCKET_YELLOW",
    "EMPTY_SOCKET_META", "EMPTY_SOCKET_PRISMATIC",
}


def translate_item_stats(raw_stats):
    """Convert GetItemStats keys to human-readable names, filtering empty sockets."""
    if not raw_stats or not isinstance(raw_stats, dict):
        return None
    out = {}
    for k, v in raw_stats.items():
        if k in _EMPTY_SOCKET_KEYS:
            continue
        human = ITEM_MOD_MAP.get(k, k)
        out[human] = v
    return out or None


# ============================================================
# Build snapshot
# ============================================================

def build_snapshot(char_globals, account_globals):
    cdb  = char_globals.get("CipherCharDB", {}) or {}
    adb  = account_globals.get("CipherDB", {}) or {}

    char_info   = cdb.get("character", {}) or {}
    gear_raw    = cdb.get("gear", {}) or {}
    bags_raw    = cdb.get("bags", {}) or {}
    bank_raw    = cdb.get("bank", {}) or {}
    talents_raw = cdb.get("talents", {}) or {}
    profs_raw   = cdb.get("professions", []) or []
    prices_raw  = adb.get("prices", {}) or {}

    # Gear: decode item links (new format: {link, stats}; old format: plain string)
    gear = {}
    for slot, slot_data in gear_raw.items():
        if isinstance(slot_data, dict):
            link = slot_data.get("link")
            raw_stats = slot_data.get("stats")
        else:
            link = slot_data
            raw_stats = None
        decoded = decode_link(link)
        if decoded:
            stats = translate_item_stats(raw_stats)
            if stats:
                decoded["stats"] = stats
            gear[str(slot)] = decoded

    # Bags: decode item links, keep count
    def decode_container(raw):
        out = {}
        for bag_id, slots in raw.items():
            if not isinstance(slots, dict):
                continue
            bag_out = {}
            for slot_id, entry in slots.items():
                if isinstance(entry, dict):
                    decoded = decode_link(entry.get("link"))
                    if decoded:
                        decoded["count"] = entry.get("count", 1)
                        stats = translate_item_stats(entry.get("stats"))
                        if stats:
                            decoded["stats"] = stats
                        bag_out[str(slot_id)] = decoded
            if bag_out:
                out[str(bag_id)] = bag_out
        return out

    bags = decode_container(bags_raw)
    bank = decode_container(bank_raw)

    # Talents: handle both old (list of trees) and new (list of specs with trees) format.
    # New format: talents_raw = [{active, trees: [{name, pointsSpent, talents}]}]
    # Old format: talents_raw = {1: {name, pointsSpent, talents}}
    def _parse_tree(tree):
        talent_list = tree.get("talents", {})
        if isinstance(talent_list, dict):
            talent_list = list(talent_list.values())
        return {
            "tree":        tree.get("name", "?"),
            "pointsSpent": tree.get("pointsSpent", 0),
            "talents":     talent_list,
        }

    def _rows(raw):
        if isinstance(raw, list):
            return raw
        if isinstance(raw, dict):
            return [raw[k] for k in sorted(raw.keys())]
        return []

    first = _rows(talents_raw)[0] if _rows(talents_raw) else {}
    is_dual_spec_format = isinstance(first, dict) and "trees" in first

    talents = []
    if is_dual_spec_format:
        for spec in _rows(talents_raw):
            if not isinstance(spec, dict):
                continue
            spec_trees = [_parse_tree(t) for t in _rows(spec.get("trees", {})) if isinstance(t, dict)]
            talents.append({
                "active": spec.get("active", False),
                "trees":  spec_trees,
            })
    else:
        trees = [_parse_tree(t) for t in _rows(talents_raw) if isinstance(t, dict)]
        if trees:
            talents.append({"active": True, "trees": trees})

    # Professions
    professions = []
    if isinstance(profs_raw, dict):
        profs_raw = list(profs_raw.values())
    for p in profs_raw:
        if isinstance(p, dict) and p.get("name"):
            professions.append({
                "name":     p["name"],
                "level":    p.get("level", 0),
                "maxLevel": p.get("maxLevel", 0),
            })

    # Prices: convert to {itemID: {copper, gold}} dict
    prices = {}
    for item_id, copper in prices_raw.items():
        if isinstance(copper, int) and copper > 0:
            prices[str(item_id)] = {
                "copper": copper,
                "gold":   copper_to_gold(copper),
            }

    # TSM prices: {itemID: {dbmarket, dbminbuyout}} with gold strings added
    tsm_raw = cdb.get("tsmPrices", {}) or {}
    tsm_prices = {}
    for item_id, price_data in tsm_raw.items():
        if not isinstance(price_data, dict):
            continue
        entry = {}
        market = price_data.get("dbmarket")
        minbuyout = price_data.get("dbminbuyout")
        if isinstance(market, int) and market > 0:
            entry["dbmarket"]      = market
            entry["dbmarket_gold"] = copper_to_gold(market)
        if isinstance(minbuyout, int) and minbuyout > 0:
            entry["dbminbuyout"]      = minbuyout
            entry["dbminbuyout_gold"] = copper_to_gold(minbuyout)
        if entry:
            tsm_prices[str(item_id)] = entry

    # Exported timestamps → human-readable UTC
    def ts(val):
        if not val or not isinstance(val, int):
            return None
        try:
            return datetime.fromtimestamp(val, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        except (OSError, OverflowError):
            return None

    snapshot = {
        "meta": {
            "character":       char_info.get("name"),
            "realm":           char_info.get("realm"),
            "level":           char_info.get("level"),
            "class":           char_info.get("class"),
            "race":            char_info.get("race"),
            "faction":         char_info.get("faction"),
            "exportedAt":      ts(char_info.get("exportedAt")),
            "bankUpdatedAt":   ts(cdb.get("bankUpdatedAt")),
            "priceRealm":      adb.get("priceRealm"),
            "priceCount":      adb.get("priceCount"),
            "priceUpdatedAt":  ts(adb.get("priceUpdatedAt")),
        },
        "talents":     talents,
        "professions": professions,
        "gear":        gear,
        "bags":        bags,
        "bank":        bank,
        "prices":      prices,
        "tsmPrices":   tsm_prices,
    }
    return snapshot


# ============================================================
# Main
# ============================================================

def find_char_svs():
    """Return list of (char_name, realm_name, path) for all Cipher per-char saves."""
    results = []
    if not WTF_ACCOUNT.exists():
        return results
    for realm_dir in WTF_ACCOUNT.iterdir():
        if not realm_dir.is_dir() or realm_dir.name == "SavedVariables":
            continue
        for char_dir in realm_dir.iterdir():
            sv = char_dir / "SavedVariables/Cipher.lua"
            if sv.exists():
                results.append((char_dir.name, realm_dir.name, sv))
    return results


def main():
    filter_char = None
    if "--char" in sys.argv:
        idx = sys.argv.index("--char")
        if idx + 1 < len(sys.argv):
            filter_char = sys.argv[idx + 1].lower()

    EXPORTS_DIR.mkdir(exist_ok=True)

    # Account-level SavedVariables (prices)
    print(f"Reading account data: {ACCOUNT_SV}")
    account_globals = parse_lua_file(ACCOUNT_SV)
    if not account_globals:
        print("  No account data found. Log in and run /cipher first.")

    # Per-character SavedVariables
    char_svs = find_char_svs()
    if not char_svs:
        print("No per-character Cipher data found. Log in and run /cipher first.")
        return

    written = []
    for char_name, realm_name, sv_path in sorted(char_svs):
        if filter_char and char_name.lower() != filter_char:
            continue

        print(f"Processing {char_name} @ {realm_name} ...")
        char_globals = parse_lua_file(sv_path)
        snapshot     = build_snapshot(char_globals, account_globals)

        char_meta = snapshot["meta"]
        if not char_meta.get("character"):
            print(f"  Skipping — no character data in save.")
            continue

        ts_str   = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"snapshot_{ts_str}_{char_name.lower()}.json"
        out_path = EXPORTS_DIR / filename

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False)

        price_count = char_meta.get("priceCount", 0)
        gear_count  = len(snapshot["gear"])
        print(f"  Written: {out_path}")
        print(f"  Gear slots: {gear_count}  |  AH prices: {price_count}")
        written.append(out_path)

    if not written:
        print("Nothing written. Use --char <name> to filter, or log in and run /cipher.")
    else:
        print(f"\nDone. {len(written)} snapshot(s) in {EXPORTS_DIR}")
        print("Paste the JSON file contents to Claude for analysis.")


if __name__ == "__main__":
    main()
