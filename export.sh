#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

echo "=== Parsing SavedVariables ==="
python3 parse.py

echo ""
echo "=== Pruning old snapshots (keeping latest per character) ==="
python3 - <<'EOF'
from pathlib import Path
from collections import defaultdict

exports = Path("exports")
by_char = defaultdict(list)

for f in exports.glob("snapshot_*.json"):
    if "_enriched" in f.name:
        continue
    char = f.stem.rsplit("_", 1)[-1]
    by_char[char].append(f)

for char, files in by_char.items():
    files.sort(reverse=True)
    for old in files[1:]:
        old.unlink()
        enriched = old.parent / old.name.replace(".json", "_enriched.json")
        if enriched.exists():
            enriched.unlink()
        print(f"  Removed {old.name}")
EOF

echo ""
echo "=== Enriching with Wowhead item stats ==="
python3 enrich.py

echo ""
echo "=== Generating character briefings ==="
python3 summarize.py

echo ""
echo "Done."
