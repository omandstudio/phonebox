# PhoneBox macOS Companion & Fork Enhancements

This directory contains the custom macOS companion tools and web panel enhancements built on top of [`ersinkoc/phonebox`](https://github.com/ersinkoc/phonebox).

## ✨ Added Features

1. **🔊 External Speaker (MacBook → Android / iPhone)**
   - Captures full macOS 13+ system audio output using native **`ScreenCaptureKit`** (`mac_audio_capture.swift`), with automatic silence keep-alive so mobile browsers never drop the stream.
   - Encodes and broadcasts a low-delay `192 kbps` MP3 stream on `/api/audio/stream.mp3` via `ffmpeg` (started on-demand only when a phone activates External Speaker).
   - Adds a Cast / External Speaker toggle button directly inside the **Media** widget (`extracted_resources/www/`).

2. **📱 iPhone / iOS Safari PWA Compatibility**
   - LAN Wi-Fi bridge (`iphone_bridge.py` on port `8766`) with automatic Mac LAN IP detection.
   - Apple Mobile Web App PWA (`manifest.json`, `apple-touch-icon.png`, `viewport-fit=cover`, safe-area Notch/Dynamic Island padding, `100dvh`, WakeLock, and AudioContext micro-haptics in `compat.js`).

3. **🎵 Native Apple Music (`Music.app`) Controller**
   - Live Now-Playing title, artist, album, position, duration, and album artwork (`/api/art?id=apple_music`) using JXA (`osascript -l JavaScript`).
   - Full playback control (`play`, `pause`, `playpause`, `next`, `prev`, `seek`).

4. **🤖 Android USB Bridge & One-Click Launchers**
   - Automatic `adb reverse` loop (`tcp:8765 -> tcp:8766` and `tcp:8766 -> tcp:8766`) so Android devices over USB receive the enhanced panel and audio stream.
   - `Start-PhoneBox.command` / `Stop-PhoneBox.command` for terminal-free launching on macOS.

---

## 🚀 Setup & Usage (macOS 13+)

### 1. Compile the Native Audio Capture Helper
```bash
cd macos-companion
swiftc -parse-as-library -target x86_64-apple-macos13.0 \
  -framework ScreenCaptureKit -framework AVFoundation -framework CoreMedia -framework CoreGraphics \
  mac_audio_capture.swift -o mac_audio_capture
codesign -s - -f mac_audio_capture
```
*(Ensure `ffmpeg` is installed or available in `PATH` or `bin/ffmpeg`).*

### 2. Start PhoneBoxAgent & the Companion Bridge
```bash
python3 iphone_bridge.py
```

### 3. Connect Your Device
- **iPhone (Wi-Fi)**: Open `http://<MAC_LAN_IP>:8766/panel/index.html` in Safari → tap **Share** → **Add to Home Screen**.
- **Android (USB / Wi-Fi)**: Open `http://127.0.0.1:8766/panel/index.html` (via USB) or `http://<MAC_LAN_IP>:8766/panel/index.html` (via Wi-Fi).
- **External Speaker**: Tap the **Cast / Speaker** icon on the Media widget. On first use, grant **Screen Recording** permission in **System Settings → Privacy & Security → Screen Recording**.
