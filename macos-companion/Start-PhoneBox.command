#!/bin/bash
# Start-PhoneBox.command
# Klik 2x file ini di Finder untuk menjalankan PhoneBox

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "=================================================="
echo "📱 Memulai PhoneBox Desk Panel..."
echo "=================================================="

# Jalankan aplikasi native PhoneBox.app
open "$DIR/PhoneBox.app"

