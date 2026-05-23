#!/usr/bin/env bash
# Copies the Cipher addon to the WoW TBC Anniversary AddOns directory.

ADDONS_DIR="/home/lrabbets/.local/share/Steam/steamapps/compatdata/3579333542/pfx/drive_c/Program Files (x86)/World of Warcraft/_anniversary_/Interface/AddOns"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$SCRIPT_DIR/addon"
DEST="$ADDONS_DIR/Cipher"

if [ ! -d "$ADDONS_DIR" ]; then
    echo "Error: AddOns directory not found: $ADDONS_DIR"
    exit 1
fi

echo "Installing Cipher addon..."
rm -rf "$DEST"
cp -r "$SRC" "$DEST"
echo "Done: $DEST"
echo ""
echo "Next steps:"
echo "  1. Launch WoW and log in to a character"
echo "  2. Make sure Cipher is enabled on the character select screen"
echo "  3. Data is exported automatically on login"
echo "  4. Type /cipher in-game to force a re-export"
echo "  5. Visit the bank to capture bank contents"
echo "  6. Log out, then run: python3 parse.py"
