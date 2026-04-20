import asyncio
import json
import os
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

VIDEOS_DIR = os.path.join(os.path.dirname(__file__), 'videos')
MPV_PATH = 'mpv'
SCREEN_COUNT = 3

os.makedirs(os.path.join(os.path.dirname(__file__), 'mpv_sockets'), exist_ok=True)

class MPVPlayer:
    def __init__(self, screen_id: int, socket_path: str):
        self.screen_id = screen_id
        self.socket_path = socket_path
        self.process: Optional[subprocess.Popen] = None
        self.state = 'stopped'
        self.current_video = None
        self.volume = 100

    def start(self, video_path: str, loop: bool = True):
        self.stop()
        self.current_video = video_path

        loop_arg = 'inf' if loop else 'no'

        shell_cmd = (
            f'mpv "{video_path}" --loop={loop_arg} --screen={self.screen_id} '
            f'--fullscreen --hwdec=auto --volume={self.volume} --idle=no '
            f'--autofit=100% --keepaspect=no'
        )

        try:
            subprocess.Popen(shell_cmd, shell=True)
            self.state = 'playing'
            print(f"[MPV-{self.screen_id}] Started: {Path(video_path).name} on screen {self.screen_id}")
        except Exception as e:
            print(f"[MPV-{self.screen_id}] ERROR: {e}")
            self.state = 'error'

    def stop(self):
        try:
            subprocess.run(['pkill', '-f', f'mpv.*{Path(self.current_video).name}'], timeout=2)
        except:
            pass
        self.process = None
        self.state = 'stopped'

    def pause(self):
        if self.state != 'playing':
            return
        ok = self._send_command({'command': ['set', 'pause', 'yes']})
        if ok:
            self.state = 'paused'

    def resume(self):
        if self.state != 'paused':
            return
        ok = self._send_command({'command': ['set', 'pause', 'no']})
        if ok:
            self.state = 'playing'

    def set_volume(self, volume: int):
        self.volume = max(0, min(100, volume))
        self._send_command({'command': ['set', 'volume', self.volume]})

    def _send_command(self, cmd: dict, retries: int = 5) -> bool:
        for attempt in range(retries):
            try:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.settimeout(2.0)
                sock.connect(self.socket_path)
                sock.sendall((json.dumps(cmd) + '\n').encode())
                sock.close()
                return True
            except FileNotFoundError:
                if attempt < retries - 1:
                    time.sleep(0.2)
                else:
                    pass
            except Exception as e:
                if attempt == retries - 1:
                    pass
                break
        return False

    def get_status(self) -> dict:
        running = self.process is not None and self.process.poll() is None
        if not running and self.state != 'error':
            self.state = 'stopped'
        return {
            'screen_id': self.screen_id,
            'state': self.state,
            'video': self.current_video,
            'volume': self.volume,
        }


class ScreenManager:
    def __init__(self, videos_dir: str = VIDEOS_DIR):
        self.videos_dir = videos_dir
        self.players: dict[int, MPVPlayer] = {}
        self._socket_dir = os.path.join(os.path.dirname(__file__), 'mpv_sockets')
        os.makedirs(self._socket_dir, exist_ok=True)
        self._init_players()

    def _init_players(self):
        for i in range(SCREEN_COUNT):
            socket_path = os.path.join(self._socket_dir, f'mpv_screen_{i}.sock')
            self.players[i] = MPVPlayer(screen_id=i, socket_path=socket_path)

    def scan_videos(self) -> list[str]:
        if not os.path.exists(self.videos_dir):
            return []
        videos = []
        for ext in ['*.mp4', '*.mov', '*.mkv', '*.avi', '*.m4v']:
            videos.extend(Path(self.videos_dir).glob(ext))
        return [str(v) for v in sorted(videos)]

    def get_status(self) -> dict:
        return {
            'screens': {i: p.get_status() for i, p in self.players.items()},
            'videos': self.scan_videos(),
            'videos_dir': self.videos_dir,
        }

    def play_all(self, videos: list[str] = None):
        available = self.scan_videos()
        if not available:
            print("[ScreenManager] No videos found in:", self.videos_dir)
            return
        for i, player in self.players.items():
            if videos and i < len(videos) and os.path.exists(videos[i]):
                player.start(videos[i])
            elif available:
                idx = i % len(available)
                player.start(available[idx])
            else:
                player.stop()

    def pause_all(self):
        for player in self.players.values():
            player.pause()

    def resume_all(self):
        for player in self.players.values():
            player.resume()

    def stop_all(self):
        try:
            subprocess.run(['pkill', '-9', 'mpv'], timeout=3)
        except:
            pass
        for player in self.players.values():
            player.state = 'stopped'
            player.process = None
            player.current_video = None

    def play_screen(self, screen_id: int, video_path: str = None):
        if screen_id not in self.players:
            return
        if video_path and os.path.exists(video_path):
            self.players[screen_id].start(video_path)
        else:
            available = self.scan_videos()
            if available:
                idx = screen_id % len(available)
                self.players[screen_id].start(available[idx])

    def pause_screen(self, screen_id: int):
        if screen_id in self.players:
            self.players[screen_id].pause()

    def resume_screen(self, screen_id: int):
        if screen_id in self.players:
            self.players[screen_id].resume()

    def stop_screen(self, screen_id: int):
        if screen_id in self.players:
            self.players[screen_id].stop()

    def set_volume_screen(self, screen_id: int, volume: int):
        if screen_id in self.players:
            self.players[screen_id].set_volume(volume)

    def cleanup(self):
        self.stop_all()
        try:
            import shutil
            shutil.rmtree(self._socket_dir)
        except:
            pass


_manager: Optional[ScreenManager] = None

def get_manager() -> ScreenManager:
    global _manager
    if _manager is None:
        _manager = ScreenManager()
    return _manager