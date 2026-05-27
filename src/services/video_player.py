import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from services.audio_player import audio_service

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
SCREEN_IDS = [0, 1]

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

        # Paths for EOF detection via Lua script.
        # The Lua script writes a flag file only on natural video end (EOF),
        # not on user quit (Alt+F4), so _loop_monitor can tell the two apart.
        self._eof_flag_path = os.path.join(SOCKET_DIR, f"mpv_eof_{screen_id}.flag")
        self._lua_script_path = os.path.join(SOCKET_DIR, f"mpv_eof_{screen_id}.lua")
        self._write_lua_script()

    def _write_lua_script(self) -> None:
        """Write the Lua helper that signals a natural EOF to Python."""
        # Lua needs forward slashes (works on Windows too).
        flag_path = self._eof_flag_path.replace("\\", "/")
        lua = (
            'mp.register_event("end-file", function(event)\n'
            '    if event.reason == "eof" then\n'
            f'        local f = io.open("{flag_path}", "w")\n'
            '        if f then f:write("1") f:close() end\n'
            "    end\n"
            "end)\n"
        )
        with open(self._lua_script_path, "w") as fh:
            fh.write(lua)

    def start(self, video_path: str, loop: bool = True):
        """
        Start playing a video on this screen.
        """
        self.stop()
        self.current_video = video_path

        # Remove any stale EOF flag left over from a previous run.
        try:
            os.remove(self._eof_flag_path)
        except FileNotFoundError:
            pass

        loop_arg = "no"
        # Forward slashes work in mpv --script on Windows.
        lua_path = self._lua_script_path.replace("\\", "/")

        shell_cmd = (
            f'{MPV_PATH} "{video_path}" '
            f"--loop={loop_arg} "
            f"--screen={self.screen_id} "
            f"--fullscreen "
            f"--hwdec=auto "
            f"--volume={self.volume} "
            f"--idle=no "
            f"--autofit=100% "
            f"--keepaspect=no "
            f'--script="{lua_path}"'
        )

        try:
            self.process = subprocess.Popen(shell_cmd, shell=True)
            self.state = "playing"
            if loop:
                threading.Thread(
                    target=self._loop_monitor,
                    daemon=True,
                ).start()
            print(
                f"[MPV-{self.screen_id}] Started: "
                f"{Path(video_path).name} on screen {self.screen_id}"
            )
        except Exception as e:
            print(f"[MPV-{self.screen_id}] ERROR: {e}")
            self.state = "error"

    def _loop_monitor(self):
        """
        Wait for mpv to exit, then decide whether to restart:
        - Natural EOF  → reset audio timeline and restart the video.
        - User quit (Alt+F4, window close, etc.) → leave the screen black.
        - API stop() → self.process is None; exit silently.

        The distinction between EOF and user-quit is made via a Lua script
        that writes a flag file *only* when the video ends naturally.
        """
        process_ref = self.process
        if process_ref is None:
            return

        process_ref.wait()  # Block until mpv exits for any reason.

        # stop() was called from outside — don't restart.
        if self.process is None:
            return

        if os.path.exists(self._eof_flag_path):
            # Natural end: clean up flag, reset audio, loop the video.
            try:
                os.remove(self._eof_flag_path)
            except OSError:
                pass
            print(f"[MPV-{self.screen_id}] Video ended naturally — restarting.")
            audio_service.reset()
            video = self.current_video
            if video:
                self.start(video, loop=True)
        else:
            # User closed the window (Alt+F4, etc.) — stay stopped.
            print(
                f"[MPV-{self.screen_id}] Window closed by user — "
                "staying stopped until API restart."
            )
            self.process = None
            self.state = "stopped"
            self.current_video = None

    def stop(self):
        """
        Stop the currently playing video on this screen.
        Sets self.process = None *before* killing so _loop_monitor knows
        this was an intentional stop and won't restart.
        """
        process = self.process
        self.process = None
        self.state = "stopped"
        self.current_video = None

        if process is not None:
            try:
                if sys.platform == "win32":
                    # Kill the whole process tree (cmd.exe shell + mpv child).
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                        capture_output=True,
                        timeout=3,
                    )
                else:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
            except Exception:
                pass

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
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/IM", "mpv.exe"],
                    capture_output=True,
                    timeout=3,
                )
            else:
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

    def play_screen(self, screen_id: int, video_path: str | None = None):
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
