#!/bin/bash
# Stop-PhoneBox.command
# Klik 2x file ini di Finder untuk menghentikan PhoneBox dan Bridge

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "=================================================="
echo "🛑 Menghentikan PhoneBox Desk Panel & Bridge..."
echo "=================================================="

pkill -f "PhoneBoxAgent" 2>/dev/null
pkill -f "iphone_bridge.py" 2>/dev/null

osascript -e 'display notification "PhoneBoxAgent dan Bridge berhasil dihentikan." with title "PhoneBox Dihentikan" sound name "Pop"' 2>/dev/null

echo "✅ PhoneBox berhasil dihentikan."
sleep 1

