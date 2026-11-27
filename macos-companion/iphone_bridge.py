#!/usr/bin/env python3
"""
PhoneBox iPhone Companion, Media Controller & LAN Bridge (v3)
=============================================================
- Full native integration with Apple Music (Music.app on macOS):
  * Live Now-Playing metadata (Title, Artist, Album, Position, Duration, Play/Pause state)
  * Hardware/Software Media controls: Play, Pause, Play/Pause toggle, Next Track, Previous Track, Seek
  * Live Album Artwork streaming & caching (/api/art?id=apple_music)
- Full iPhone Web App PWA support with safe areas, touch haptics & wakeLock
- Root-level asset fallback preventing any "LOAD FAIL" errors
- LAN bridge enabling seamless iPhone access over Wi-Fi
- Decorates /api/info with connected=True, via="Wi-Fi (iPhone)"
"""

import os
import sys
import time
import json
import queue
import shutil
import socket
import threading
import subprocess
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, 'extracted_resources', 'www')
AGENT_HOST = '127.0.0.1'
AGENT_PORT = 8765
BRIDGE_PORT = 8766

# Track when an iPhone last communicated with the bridge
last_iphone_activity = 0

# Music state cache to prevent excessive osascript executions
music_cache = {
    'time': 0,
    'data': None,
    'art_cache': None,
    'art_track': None
}

def get_apple_music_state():
    """Query Apple Music status via JXA (JavaScript for Automation)"""
    now = time.time()
    if now - music_cache['time'] < 0.6:
        return music_cache['data']

    jxa = '''
    function run() {
      try {
        var music = Application("Music");
        if (!music.running()) return JSON.stringify({ active: false });
        var pState = music.playerState();
        if (pState === "stopped") return JSON.stringify({ active: false, playerState: "stopped" });
        var t = music.currentTrack();
        var name = "";
        var artist = "";
        var album = "";
        var dur = 0;
        var pos = 0;
        try { name = t.name() || ""; } catch(_) {}
        try { artist = t.artist() || ""; } catch(_) {}
        try { album = t.album() || ""; } catch(_) {}
        try { dur = t.duration() || 0; } catch(_) {}
        try { pos = music.playerPosition() || 0; } catch(_) {}
        
        var hasArt = false;
        try {
          var arts = t.artworks();
          hasArt = (arts && arts.length > 0);
        } catch(_) {}

        return JSON.stringify({
          active: true,
          app: "Music",
          title: name,
          artist: artist,
          album: album,
          playing: (pState === "playing"),
          posMs: Math.round(pos * 1000),
          durMs: Math.round(dur * 1000),
          canSeek: true,
          hasArt: hasArt
        });
      } catch (e) {
        return JSON.stringify({ active: false, error: e.message });
      }
    }
    '''
    try:
        p = subprocess.run(
            ['osascript', '-l', 'JavaScript', '-e', jxa],
            capture_output=True,
            text=True,
            timeout=2.0
        )
        if p.returncode == 0 and p.stdout.strip():
            res = json.loads(p.stdout.strip())
            music_cache['time'] = now
            music_cache['data'] = res
            return res
    except Exception:
        pass

    return {'active': False}

def control_apple_music(action, query_params=''):
    """Send playback control commands to Apple Music"""
    jxa = ''
    clean_action = action.split('?')[0].lower()

    if clean_action in ('playpause', 'toggle'):
        jxa = 'Application("Music").playpause();'
    elif clean_action == 'play':
        jxa = 'Application("Music").play();'
    elif clean_action == 'pause':
        jxa = 'Application("Music").pause();'
    elif clean_action in ('next', 'nexttrack'):
        jxa = 'Application("Music").nextTrack();'
    elif clean_action in ('prev', 'previous', 'prevtrack'):
        jxa = 'Application("Music").previousTrack();'
    elif clean_action.startswith('seek'):
        ms = 0
        search_target = query_params if query_params else action
        if 'ms=' in search_target:
            try:
                ms = int(search_target.split('ms=')[1].split('&')[0])
            except ValueError:
                ms = 0
        sec = max(0, ms / 1000.0)
        jxa = f'Application("Music").playerPosition = {sec};'

    if jxa:
        try:
            subprocess.run(
                ['osascript', '-l', 'JavaScript', '-e', f'try {{ if (Application("Music").running()) {{ {jxa} }} }} catch (_) {{}}'],
                capture_output=True,
                timeout=2.0
            )
        except Exception:
            pass

    # Force fresh read
    music_cache['time'] = 0
    return get_apple_music_state()

def get_apple_music_artwork():
    """Extract album artwork binary from Apple Music"""
    state = get_apple_music_state()
    if not state or not state.get('active') or not state.get('hasArt'):
        return None

    track_key = f"{state.get('title')}-{state.get('artist')}"
    if music_cache.get('art_track') == track_key and music_cache.get('art_cache'):
        return music_cache['art_cache']

    temp_art = '/tmp/phonebox_music_art.jpg'
    as_script = f'''
    try
      tell application "Music"
        if player state is not stopped then
          set artData to raw data of artwork 1 of current track
          set fp to open for access POSIX file "{temp_art}" with write permission
          set eof of fp to 0
          write artData to fp
          close access fp
          return "OK"
        end if
      end tell
    on error
      try
        close access POSIX file "{temp_art}"
      end try
      return ""
    end try
    '''
    try:
        p = subprocess.run(['osascript', '-e', as_script], capture_output=True, text=True, timeout=3.0)
        if 'OK' in p.stdout and os.path.exists(temp_art):
            with open(temp_art, 'rb') as f:
                data = f.read()
            if len(data) > 0:
                music_cache['art_cache'] = data
                music_cache['art_track'] = track_key
                return data
    except Exception:
        pass

    return None

def format_media_snapshot(m_state):
    """Format state into PhoneBox MediaSnapshot format"""
    if not m_state or not m_state.get('active'):
        return None
    art_id = f"music_{abs(hash(m_state.get('title', '') + m_state.get('artist', '')))}" if m_state.get('hasArt') else None
    return {
        'app': 'Music',
        'title': m_state.get('title') or 'Unknown Title',
        'artist': m_state.get('artist') or '',
        'album': m_state.get('album') or '',
        'playing': m_state.get('playing', False),
        'posMs': m_state.get('posMs', 0),
        'durMs': m_state.get('durMs', 0),
        'artId': art_id,
        'canSeek': True
    }

def get_lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('1.1.1.1', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

class AudioStreamManager:
    """Manages on-demand macOS system audio capture -> MP3 broadcast to connected clients."""
    def __init__(self):
        self.lock = threading.Lock()
        self.clients = []
        self.capture_proc = None
        self.ffmpeg_proc = None
        self.reader_thread = None
        self.running = False
        self.last_error = None
        self.permission_required = False

    def find_ffmpeg(self):
        ff = shutil.which('ffmpeg')
        if ff:
            return ff
        candidates = [
            os.path.join(BASE_DIR, 'bin', 'ffmpeg'),
            os.path.join(os.path.dirname(BASE_DIR), 'remotion', 'bin', 'ffmpeg'),
            '/usr/local/bin/ffmpeg',
            '/opt/homebrew/bin/ffmpeg',
        ]
        for c in candidates:
            if os.path.isfile(c) and os.access(c, os.X_OK):
                return c
        return None

    def find_capture_bin(self):
        c = os.path.join(BASE_DIR, 'mac_audio_capture')
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
        return None

    def status(self):
        with self.lock:
            return {
                'available': bool(self.find_ffmpeg() and self.find_capture_bin()),
                'active': self.running,
                'clients': len(self.clients),
                'error': self.last_error,
                'permissionRequired': self.permission_required,
            }

    def subscribe(self):
        q = queue.Queue(maxsize=64)
        with self.lock:
            self.clients.append(q)
            if not self.running:
                self._start_locked()
        return q

    def unsubscribe(self, q):
        with self.lock:
            if q in self.clients:
                self.clients.remove(q)
            if not self.clients and self.running:
                self._stop_locked()

    def _start_locked(self):
        capture_bin = self.find_capture_bin()
        ffmpeg_bin = self.find_ffmpeg()
        if not capture_bin or not ffmpeg_bin:
            self.last_error = 'Audio capture binary or ffmpeg not found'
            return

        self.last_error = None
        self.permission_required = False
        try:
            self.capture_proc = subprocess.Popen(
                [capture_bin],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0
            )
            self.ffmpeg_proc = subprocess.Popen(
                [
                    ffmpeg_bin,
                    '-hide_banner', '-loglevel', 'error',
                    '-f', 's16le', '-ar', '48000', '-ac', '2',
                    '-i', 'pipe:0',
                    '-c:a', 'libmp3lame', '-b:a', '192k',
                    '-fflags', '+nobuffer', '-flags', '+low_delay',
                    '-flush_packets', '1',
                    '-f', 'mp3', 'pipe:1'
                ],
                stdin=self.capture_proc.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0
            )
            self.capture_proc.stdout.close()
            self.running = True
            self.reader_thread = threading.Thread(target=self._read_loop, daemon=True)
            self.reader_thread.start()
            threading.Thread(target=self._watch_stderr, args=(self.capture_proc,), daemon=True).start()
        except Exception as e:
            self.last_error = str(e)
            self._stop_locked()

    def _watch_stderr(self, proc):
        try:
            for line in iter(proc.stderr.readline, b''):
                text = line.decode('utf-8', 'ignore').strip()
                if 'ERROR_PERMISSION' in text or 'declined TCCs' in text:
                    with self.lock:
                        self.permission_required = True
                        self.last_error = 'Izin Screen Recording diperlukan di System Settings > Privacy & Security > Screen Recording'
                elif text.startswith('ERROR:'):
                    with self.lock:
                        self.last_error = text
        except Exception:
            pass

    def _read_loop(self):
        ff = self.ffmpeg_proc
        while self.running and ff and ff.stdout:
            try:
                chunk = ff.stdout.read(2048)
                if not chunk:
                    break
                with self.lock:
                    dead = []
                    for q in self.clients:
                        try:
                            q.put_nowait(chunk)
                        except queue.Full:
                            try:
                                q.get_nowait()
                                q.put_nowait(chunk)
                            except Exception:
                                dead.append(q)
                    for d in dead:
                        if d in self.clients:
                            self.clients.remove(d)
            except Exception:
                break
        with self.lock:
            self._stop_locked()

    def _stop_locked(self):
        self.running = False
        for proc in (self.ffmpeg_proc, self.capture_proc):
            if proc:
                try:
                    proc.terminate()
                except Exception:
                    pass
                try:
                    proc.kill()
                except Exception:
                    pass
        self.ffmpeg_proc = None
        self.capture_proc = None
        for q in self.clients:
            try:
                q.put_nowait(None)
            except Exception:
                pass


audio_manager = AudioStreamManager()


def adb_reverse_loop():
    """Keep ADB reverse tunnels pointed to the bridge (8766) so Android APK gets External Speaker & Apple Music."""
    adb_bin = os.path.join(BASE_DIR, 'platform-tools', 'adb')
    if not os.path.isfile(adb_bin):
        adb_bin = shutil.which('adb')
    if not adb_bin:
        return
    while True:
        try:
            out = subprocess.check_output([adb_bin, 'reverse', '--list'], stderr=subprocess.DEVNULL, timeout=3).decode('utf-8', 'ignore')
            if 'tcp:8765 tcp:8766' not in out:
                subprocess.run([adb_bin, 'reverse', 'tcp:8765', 'tcp:8766'], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL, timeout=3)
            if 'tcp:8766 tcp:8766' not in out:
                subprocess.run([adb_bin, 'reverse', 'tcp:8766', 'tcp:8766'], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL, timeout=3)
        except Exception:
            pass
        time.sleep(4)


class PhoneBoxIPhoneHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        self.handle_request('GET')

    def do_HEAD(self):
        self.handle_request('HEAD')

    def do_POST(self):
        self.handle_request('POST')

    def do_PUT(self):
        self.handle_request('PUT')

    def do_DELETE(self):
        self.handle_request('DELETE')

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.end_headers()

    def send_json(self, data, status=200):
        body = json.dumps(data).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def handle_request(self, method):
        global last_iphone_activity
        path = self.path

        # Parse query string and clean path
        clean_path = path.split('?')[0]
        query_str = path.split('?')[1] if '?' in path else ''

        # Canonicalize agent path: /agent/api/... -> /api/...
        api_path = clean_path
        if api_path.startswith('/agent/api'):
            api_path = api_path[6:] # -> /api/...

        # Track mobile/iPhone activity
        ua = self.headers.get('User-Agent', '')
        if any(k in ua for k in ('iPhone', 'iPad', 'Safari', 'Mobile')) or 'X-PhoneBox' in str(self.headers):
            last_iphone_activity = time.time()

        # 1. Root redirect to panel
        if clean_path in ('', '/', '/panel', '/panel/'):
            self.send_response(302)
            self.send_header('Location', '/panel/index.html')
            self.end_headers()
            return

        # 2. Favicon / App icons
        if clean_path in ('/phonebox.ico', '/favicon.ico'):
            ico_file = os.path.join(BASE_DIR, 'extracted_resources', 'phonebox.ico')
            if os.path.exists(ico_file):
                self.serve_local_file(ico_file, method)
                return

        # 3. Handle Media Controls: /api/media/{action} or /agent/api/media/{action}
        if api_path.startswith('/api/media/'):
            action = api_path[len('/api/media/'):]
            m_state = control_apple_music(action, query_str)
            # Forward action to agent as well in the background
            try:
                self.forward_bg_to_agent(method, path)
            except Exception:
                pass
            media_snapshot = format_media_snapshot(m_state)
            self.send_json({'media': media_snapshot})
            return

        # 4. Handle Artwork: /api/art or /agent/api/art
        if api_path == '/api/art':
            art_id = ''
            if 'id=' in query_str:
                art_id = query_str.split('id=')[1].split('&')[0]
            if art_id.startswith('music_') or art_id == 'apple_music':
                art_bytes = get_apple_music_artwork()
                if art_bytes:
                    self.send_response(200)
                    self.send_header('Content-Type', 'image/jpeg')
                    self.send_header('Content-Length', str(len(art_bytes)))
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.send_header('Cache-Control', 'public, max-age=60')
                    self.end_headers()
                    self.wfile.write(art_bytes)
                    return

        # 4b. Handle External Speaker Audio Status & Stream
        if api_path == '/api/audio/status':
            self.send_json(audio_manager.status())
            return

        if api_path in ('/api/audio/stream', '/api/audio/stream.mp3'):
            self.serve_audio_stream(method)
            return

        # 5. Intercept /api/info
        if api_path == '/api/info':
            self.proxy_api_info(method, path)
            return

        # 6. Intercept /api/state (Inject Apple Music live status)
        if api_path == '/api/state':
            self.proxy_api_state(method, path)
            return

        # 7. Serve Static Assets (from ASSETS_DIR):
        # Handles /panel/<file>, direct /<file>, and /widgets/<file>
        rel = clean_path
        if rel.startswith('/panel/'):
            rel = rel[7:]
        rel = rel.lstrip('/')

        local_file = os.path.join(ASSETS_DIR, rel)
        if rel and os.path.exists(local_file) and os.path.isfile(local_file):
            self.serve_local_file(local_file, method)
            return

        # 8. Proxy everything else to PhoneBoxAgent
        proxy_target = path
        if proxy_target.startswith('/agent/api'):
            proxy_target = proxy_target[6:]
        self.proxy_to_agent(method, proxy_target)

    def serve_audio_stream(self, method='GET'):
        self.send_response(200)
        self.send_header('Content-Type', 'audio/mpeg')
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Connection', 'close')
        self.end_headers()
        if method == 'HEAD':
            return

        q = audio_manager.subscribe()
        try:
            while True:
                try:
                    chunk = q.get(timeout=15)
                except queue.Empty:
                    if not audio_manager.running:
                        break
                    continue
                if chunk is None:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            audio_manager.unsubscribe(q)

    def serve_local_file(self, filepath, method='GET'):
        ext = os.path.splitext(filepath)[1].lower()
        content_types = {
            '.html': 'text/html; charset=utf-8',
            '.js': 'application/javascript; charset=utf-8',
            '.css': 'text/css; charset=utf-8',
            '.json': 'application/json; charset=utf-8',
            '.png': 'image/png',
            '.ico': 'image/x-icon',
            '.svg': 'image/svg+xml'
        }
        content_type = content_types.get(ext, 'application/octet-stream')

        try:
            with open(filepath, 'rb') as f:
                data = f.read()
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            if method != 'HEAD':
                self.wfile.write(data)
        except Exception as e:
            self.send_error(500, str(e))

    def proxy_api_state(self, method, path):
        """Fetch state from PhoneBoxAgent and enrich with Apple Music if active"""
        target_path = path[6:] if path.startswith('/agent/api') else path
        target_url = f"http://{AGENT_HOST}:{AGENT_PORT}{target_path}"
        req = urllib.request.Request(target_url, method=method)
        req.add_header('Host', f'{AGENT_HOST}:{AGENT_PORT}')

        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                raw_data = resp.read()
                try:
                    state_obj = json.loads(raw_data.decode('utf-8'))
                    m_state = get_apple_music_state()
                    if m_state and m_state.get('active'):
                        state_obj['media'] = format_media_snapshot(m_state)
                    body = json.dumps(state_obj).encode('utf-8')
                except Exception:
                    body = raw_data

                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(body)
        except Exception as e:
            # Fallback direct state if agent connection times out
            m_state = get_apple_music_state()
            fallback_state = {
                'media': format_media_snapshot(m_state),
                'connected': True
            }
            self.send_json(fallback_state)

    def proxy_api_info(self, method, path):
        """Fetch info from agent and enrich with iPhone connection status"""
        target_path = path[6:] if path.startswith('/agent/api') else path
        target_url = f"http://{AGENT_HOST}:{AGENT_PORT}{target_path}"
        req = urllib.request.Request(target_url, method=method)
        req.add_header('Host', f'{AGENT_HOST}:{AGENT_PORT}')

        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                raw_data = resp.read()
                try:
                    info = json.loads(raw_data.decode('utf-8'))
                    if time.time() - last_iphone_activity < 90:
                        info['connected'] = True
                        info['via'] = 'Wi-Fi (iPhone)'
                    response_bytes = json.dumps(info).encode('utf-8')
                except Exception:
                    response_bytes = raw_data

                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(response_bytes)))
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(response_bytes)
        except Exception:
            fallback_info = {
                'connected': (time.time() - last_iphone_activity < 90),
                'via': 'Wi-Fi (iPhone)',
                'version': '0.9.14'
            }
            self.send_json(fallback_info)

    def forward_bg_to_agent(self, method, target_path):
        target_url = f"http://{AGENT_HOST}:{AGENT_PORT}{target_path}"
        req = urllib.request.Request(target_url, method=method)
        req.add_header('Host', f'{AGENT_HOST}:{AGENT_PORT}')
        try:
            urllib.request.urlopen(req, timeout=1)
        except Exception:
            pass

    def proxy_to_agent(self, method, target_path):
        target_url = f"http://{AGENT_HOST}:{AGENT_PORT}{target_path}"
        body = None
        if 'Content-Length' in self.headers:
            try:
                length = int(self.headers['Content-Length'])
                body = self.rfile.read(length)
            except Exception:
                body = None

        req = urllib.request.Request(target_url, data=body, method=method)
        for h, v in self.headers.items():
            if h.lower() not in ('host', 'content-length'):
                req.add_header(h, v)
        req.add_header('Host', f'{AGENT_HOST}:{AGENT_PORT}')
        req.add_header('X-PhoneBox-Device', 'iPhone')
        req.add_header('X-PhoneBox-Model', 'Apple iPhone')
        req.add_header('X-PhoneBox-App', 'PhoneBox iOS')
        req.add_header('X-PhoneBox-Panel', '1')

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                self.send_response(resp.status)
                for h, v in resp.getheaders():
                    if h.lower() not in ('transfer-encoding',):
                        self.send_header(h, v)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(resp.read())
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            for h, v in e.headers.items():
                if h.lower() not in ('transfer-encoding',):
                    self.send_header(h, v)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(e.read())
        except Exception as e:
            self.send_error(502, f"PhoneBoxAgent proxy failed: {e}")

def main():
    lan_ip = get_lan_ip()
    threading.Thread(target=adb_reverse_loop, daemon=True).start()
    port = BRIDGE_PORT
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass

    server_address = ('0.0.0.0', port)
    ThreadingHTTPServer.daemon_threads = True
    try:
        httpd = ThreadingHTTPServer(server_address, PhoneBoxIPhoneHandler)
    except OSError:
        port = 8767
        server_address = ('0.0.0.0', port)
        httpd = ThreadingHTTPServer(server_address, PhoneBoxIPhoneHandler)

    iphone_url = f"http://{lan_ip}:{port}/panel/index.html"
    print("\n" + "=" * 65)
    print(" 📱 PHONEBOX IPHONE BRIDGE & APPLE MUSIC CONTROLLER READY")
    print("=" * 65)
    print(f"👉 Buka di iPhone Safari: {iphone_url}")
    print(f"👉 Buka di Browser Mac:  http://127.0.0.1:{port}/panel/index.html")
    print(f"👉 Mac Settings Panel:   http://127.0.0.1:{AGENT_PORT}/")
    print("=" * 65 + "\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping bridge...")

if __name__ == '__main__':
    main()
