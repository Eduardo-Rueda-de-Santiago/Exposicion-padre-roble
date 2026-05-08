import asyncio
import json
import os
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

# -----------------------------------------------------------------------------
# CONFIGURATION
# -----------------------------------------------------------------------------

# Directory containing video files
VIDEOS_DIR = os.path.join(os.path.dirname(__file__), "..", "videos")

# Path to mpv executable
MPV_PATH = "mpv"

# IMPORTANT:
# We explicitly define which screens to use.
# Screen 0 is ignored.
# We only use screens 1, 2, and 3 (i.e., physical displays 2–4)
SCREEN_IDS = [1, 2, 3]

# Directory for mpv IPC sockets (optional control channel)
SOCKET_DIR = os.path.join(os.path.dirname(__file__), "..", "mpv_sockets")
os.makedirs(SOCKET_DIR, exist_ok=True)


# -----------------------------------------------------------------------------
# MPV PLAYER CLASS (ONE INSTANCE PER SCREEN)
# -----------------------------------------------------------------------------


class MPVPlayer:
    """
    Controls a single mpv instance assigned to a specific screen.
    """

    def __init__(self, screen_id: int, socket_path: str):
        self.screen_id = screen_id
        self.socket_path = socket_path
        self.process: Optional[subprocess.Popen] = None
        self.state = "stopped"
        self.current_video = None
        self.volume = 100

    def start(self, video_path: str, loop: bool = True):
        """
        Start playing a video on this screen.
        """
        self.stop()
        self.current_video = video_path

        loop_arg = "inf" if loop else "no"

        shell_cmd = (
            f'{MPV_PATH} "{video_path}" '
            f"--loop={loop_arg} "
            f"--screen={self.screen_id} "
            f"--fullscreen "
            f"--hwdec=auto "
            f"--volume={self.volume} "
            f"--idle=no "
            f"--autofit=100% "
            f"--keepaspect=no"
        )

        try:
            subprocess.Popen(shell_cmd, shell=True)
            self.state = "playing"
            print(
                f"[MPV-{self.screen_id}] Started: "
                f"{Path(video_path).name} on screen {self.screen_id}"
            )
        except Exception as e:
            print(f"[MPV-{self.screen_id}] ERROR: {e}")
            self.state = "error"

    def stop(self):
        """
        Stop the currently playing video on this screen.
        """
        try:
            if self.current_video:
                subprocess.run(
                    ["pkill", "-f", f"mpv.*{Path(self.current_video).name}"],
                    timeout=2,
                )
        except Exception:
            pass

        self.process = None
        self.state = "stopped"

    def pause(self):
        """
        Pause playback.
        """
        if self.state != "playing":
            return

        if self._send_command({"command": ["set", "pause", "yes"]}):
            self.state = "paused"

    def resume(self):
        """
        Resume playback.
        """
        if self.state != "paused":
            return

        if self._send_command({"command": ["set", "pause", "no"]}):
            self.state = "playing"

    def set_volume(self, volume: int):
        """
        Set volume (0–100).
        """
        self.volume = max(0, min(100, volume))
        self._send_command({"command": ["set", "volume", self.volume]})

    def _send_command(self, cmd: dict, retries: int = 5) -> bool:
        """
        Send command to mpv via UNIX socket (if enabled).
        """
        for attempt in range(retries):
            try:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.settimeout(2.0)
                sock.connect(self.socket_path)
                sock.sendall((json.dumps(cmd) + "\n").encode())
                sock.close()
                return True
            except FileNotFoundError:
                time.sleep(0.2)
            except Exception:
                break
        return False

    def get_status(self) -> dict:
        """
        Return current player state.
        """
        running = self.process is not None and self.process.poll() is None
        if not running and self.state != "error":
            self.state = "stopped"

        return {
            "screen_id": self.screen_id,
            "state": self.state,
            "video": self.current_video,
            "volume": self.volume,
        }


# -----------------------------------------------------------------------------
# SCREEN MANAGER (CONTROLS ALL PLAYERS)
# -----------------------------------------------------------------------------


class ScreenManager:
    """
    Manages multiple MPV players across selected screens.
    """

    def __init__(self, videos_dir: str = VIDEOS_DIR):
        self.videos_dir = videos_dir
        self.players: dict[int, MPVPlayer] = {}
        self._socket_dir = SOCKET_DIR
        os.makedirs(self._socket_dir, exist_ok=True)
        self._init_players()

    def _init_players(self):
        """
        Initialize players ONLY for selected screen IDs.
        """
        for screen_id in SCREEN_IDS:
            socket_path = os.path.join(self._socket_dir, f"mpv_screen_{screen_id}.sock")
            self.players[screen_id] = MPVPlayer(
                screen_id=screen_id,
                socket_path=socket_path,
            )

    # -------------------------------------------------------------------------
    # VIDEO MANAGEMENT
    # -------------------------------------------------------------------------

    def scan_videos(self) -> list[str]:
        """
        Scan video directory for playable files.
        """
        if not os.path.exists(self.videos_dir):
            return []

        videos = []
        for ext in ["*.mp4", "*.mov", "*.mkv", "*.avi", "*.m4v"]:
            videos.extend(Path(self.videos_dir).glob(ext))

        return [str(v) for v in sorted(videos)]

    def get_status(self) -> dict:
        """
        Get full system status.
        """
        return {
            "screens": {i: p.get_status() for i, p in self.players.items()},
            "videos": self.scan_videos(),
            "videos_dir": self.videos_dir,
        }

    # -------------------------------------------------------------------------
    # PLAYBACK CONTROL
    # -------------------------------------------------------------------------

    def play_all(self, videos: list[str] = []):
        """
        Play videos across all configured screens.

        IMPORTANT:
        Uses sequential indexing (idx) instead of screen_id
        to avoid issues when skipping screen 0.
        """
        available = self.scan_videos()

        if not available:
            print("[ScreenManager] No videos found in:", self.videos_dir)
            return

        for idx, (screen_id, player) in enumerate(self.players.items()):
            # Use provided videos list if available
            if videos and idx < len(videos) and os.path.exists(videos[idx]):
                player.start(videos[idx])
            else:
                # Cycle through available videos
                vid_idx = idx % len(available)
                player.start(available[vid_idx])

    def pause_all(self):
        for player in self.players.values():
            player.pause()

    def resume_all(self):
        for player in self.players.values():
            player.resume()

    def stop_all(self):
        """
        Force stop all mpv instances.
        """
        try:
            subprocess.run(["pkill", "-9", "mpv"], timeout=3)
        except Exception:
            pass

        for player in self.players.values():
            player.state = "stopped"
            player.process = None
            player.current_video = None

    # -------------------------------------------------------------------------
    # SINGLE SCREEN CONTROL
    # -------------------------------------------------------------------------

    def play_screen(self, screen_id: int, video_path: str = None):
        """
        Play video on a specific screen.
        """
        if screen_id not in self.players:
            return

        if video_path and os.path.exists(video_path):
            self.players[screen_id].start(video_path)
        else:
            available = self.scan_videos()
            if available:
                # Map screen_id → index position
                idx = list(self.players.keys()).index(screen_id)
                vid_idx = idx % len(available)
                self.players[screen_id].start(available[vid_idx])

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

    # -------------------------------------------------------------------------
    # CLEANUP
    # -------------------------------------------------------------------------

    def cleanup(self):
        """
        Stop everything and remove socket directory.
        """
        self.stop_all()

        try:
            import shutil

            shutil.rmtree(self._socket_dir)
        except Exception:
            pass


# -----------------------------------------------------------------------------
# GLOBAL INSTANCE
# -----------------------------------------------------------------------------

video_service = ScreenManager()
