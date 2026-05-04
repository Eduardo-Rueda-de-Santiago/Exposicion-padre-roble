import threading
import time

import numpy as np
import sounddevice as sd
import soundfile as sf


class RemixEngine:
    """
    Plays up to N audio tracks in sync. Track 0 is the base/always-on track.
    Tracks 1..N-1 can be triggered independently and may overlap freely —
    any number can be in the foreground at the same time.

    All tracks loop silently in the background so they are always phase-synced
    when brought forward.

    Fades use a smoothstep S-curve (slow start → fast middle → slow end),
    with separate durations for fade-in and fade-out.

    Usage:
        engine = RemixEngine(["base.wav", "t2.wav", ..., "t9.wav"])
        engine.start()

        # Call from anywhere in your program:
        engine.trigger(1)   # bring track 2 forward
        engine.trigger(3)   # bring track 4 forward at the same time (overlap)

        engine.stop()
    """

    def __init__(
        self,
        files: list[str],
        # ── Volume levels ───────────────────────────────────────────────────
        base_fg_vol: float = 1.0,  # Track 0 volume when alone in foreground
        base_bg_vol: float = 0.20,  # Track 0 volume when any other track is active
        track_fg_vol: float = 0.90,  # Triggered track volume at full foreground
        track_bg_vol: float = 0.0,  # Non-triggered tracks' silent loop volume
        # ── Timing ─────────────────────────────────────────────────────────
        fade_in_duration: float = 2.0,  # Seconds to fade a track in
        fade_out_duration: float = 3.0,  # Seconds to fade a track out (longer = smoother exit)
        solo_duration: float = 5.0,  # Seconds before a triggered track auto-fades out
        # ── Audio device ────────────────────────────────────────────────────
        device=None,  # sounddevice device index or name (None = default)
        blocksize: int = 1024,  # Audio buffer size in frames
    ):
        """
        Args:
            files:             Audio file paths. Index 0 is the always-on base track.
                               All files must have the same sample rate and length.
            base_fg_vol:       Volume of track 0 when it is the only active track.
            base_bg_vol:       Volume of track 0 when at least one other track is active.
            track_fg_vol:      Volume of a triggered track while it is in the foreground.
            track_bg_vol:      Volume of tracks 1..N while not triggered (silent loop).
            fade_in_duration:  Seconds for a track to reach full foreground volume.
            fade_out_duration: Seconds for a track to return to background volume.
            solo_duration:     How long a triggered track stays in the foreground
                               before automatically fading out.
            device:            sounddevice output device (None = system default).
            blocksize:         Audio callback buffer size in frames.
        """
        self.base_fg_vol = base_fg_vol
        self.base_bg_vol = base_bg_vol
        self.track_fg_vol = track_fg_vol
        self.track_bg_vol = track_bg_vol
        self.fade_in_duration = fade_in_duration
        self.fade_out_duration = fade_out_duration
        self.solo_duration = solo_duration
        self.device = device
        self.blocksize = blocksize

        # ── Load audio ────────────────────────────────────────────────────
        self.data: list[np.ndarray] = []
        self.fs: int | None = None
        for path in files:
            samples, fs = sf.read(
                path, always_2d=True
            )  # always_2d → (frames, channels)
            self.data.append(samples.astype(np.float32))
            if self.fs is None:
                self.fs = fs

        self.n_tracks = len(self.data)
        self.track_len = len(self.data[0])  # all tracks must share this length

        # ── Per-track fade state (audio thread only, no lock needed) ──────
        # Smoothstep S-curve: each track keeps a start volume, a target volume,
        # and a fade position (0.0 = just started, 1.0 = complete).
        init_vols = np.array(
            [base_fg_vol] + [track_bg_vol] * (self.n_tracks - 1), dtype=np.float64
        )
        self._current_vols: np.ndarray = init_vols.copy()
        self._fade_from: np.ndarray = init_vols.copy()
        self._fade_target: np.ndarray = init_vols.copy()
        self._fade_pos: np.ndarray = np.ones(self.n_tracks, dtype=np.float64)

        # ── Cross-thread signaling ────────────────────────────────────────
        # Main thread writes _pending_targets under lock;
        # audio callback reads and clears it.
        self._lock = threading.Lock()
        self._pending_targets: np.ndarray | None = None

        # ── Active-track bookkeeping ──────────────────────────────────────
        self._active_tracks: set[int] = set()
        self._solo_timers: dict[int, threading.Timer] = {}

        # ── Playback ──────────────────────────────────────────────────────
        self._start_frame: int = 0
        self._stream: sd.OutputStream | None = None

    # ── Public API ─────────────────────────────────────────────────────────

    def trigger(self, track_idx: int) -> None:
        """
        Bring track_idx to the foreground.

        - Multiple tracks can be triggered simultaneously (they overlap).
        - Calling trigger() on an already-active track resets its solo timer.
        - After `solo_duration` seconds the track automatically fades out.
        - Safe to call from any thread at any time.
        """
        if not (0 < track_idx < self.n_tracks):
            return

        with self._lock:
            # Reset this track's solo timer (re-triggering extends its window)
            if track_idx in self._solo_timers:
                self._solo_timers[track_idx].cancel()

            self._active_tracks.add(track_idx)
            self._push_targets()

        timer = threading.Timer(self.solo_duration, self._deactivate, args=[track_idx])
        timer.daemon = True
        timer.start()

        with self._lock:
            self._solo_timers[track_idx] = timer

    def start(self) -> "RemixEngine":
        """Open the audio stream and begin playback. Returns self for chaining."""
        channels = self.data[0].shape[1]
        self._stream = sd.OutputStream(
            samplerate=self.fs,
            channels=channels,
            dtype="float32",
            blocksize=self.blocksize,
            device=self.device,
            callback=self._audio_callback,
        )
        self._stream.start()
        return self

    def stop(self) -> None:
        """Cancel all timers and stop the audio stream."""
        with self._lock:
            for timer in self._solo_timers.values():
                timer.cancel()
            self._solo_timers.clear()
            self._active_tracks.clear()

        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def __enter__(self) -> "RemixEngine":
        return self.start()

    def __exit__(self, *_) -> None:
        self.stop()

    # ── Internal ───────────────────────────────────────────────────────────

    def _deactivate(self, track_idx: int) -> None:
        """Called by a solo timer when a track's foreground window expires."""
        with self._lock:
            self._active_tracks.discard(track_idx)
            self._solo_timers.pop(track_idx, None)
            self._push_targets()

    def _push_targets(self) -> None:
        """
        Compute target volumes from the current active-track set and queue them
        for the audio callback. Must be called under self._lock.
        """
        targets = np.full(self.n_tracks, self.track_bg_vol, dtype=np.float64)
        targets[0] = self.base_bg_vol if self._active_tracks else self.base_fg_vol
        for i in self._active_tracks:
            targets[i] = self.track_fg_vol
        self._pending_targets = targets

    def _audio_callback(self, outdata, frames, time_info, status) -> None:
        """
        sounddevice real-time callback — runs on the audio thread.

        Fade model (per track):
          _fade_from[i]   — volume at the start of the current fade
          _fade_target[i] — volume we are heading toward
          _fade_pos[i]    — linear progress 0.0 → 1.0

        Smoothstep S-curve applied to pos:
          f(t) = 3t² − 2t³
          Zero derivative at t=0 and t=1 → no clicks, gradual ramp at both ends.
        """
        # ── Pick up any pending target change ────────────────────────────
        with self._lock:
            new_targets = self._pending_targets
            self._pending_targets = None

        if new_targets is not None:
            # Only reset tracks whose target actually changed so other fades
            # in progress continue uninterrupted.
            changed = new_targets != self._fade_target
            self._fade_from[changed] = self._current_vols[changed]
            self._fade_pos[changed] = 0.0
            self._fade_target = new_targets

        # ── Advance fade positions ────────────────────────────────────────
        # Use fade_in_duration or fade_out_duration depending on direction.
        fading_in = self._fade_target >= self._fade_from
        step = np.where(
            fading_in,
            frames / (self.fade_in_duration * self.fs),
            frames / (self.fade_out_duration * self.fs),
        )
        self._fade_pos = np.clip(self._fade_pos + step, 0.0, 1.0)

        # ── Smoothstep S-curve: f(t) = 3t² − 2t³ ────────────────────────
        t = self._fade_pos**2 * (3.0 - 2.0 * self._fade_pos)
        self._current_vols = self._fade_from + (self._fade_target - self._fade_from) * t

        # ── Mix all tracks ────────────────────────────────────────────────
        indices = (
            np.arange(self._start_frame, self._start_frame + frames) % self.track_len
        )
        self._start_frame += frames

        mixed = sum(
            self.data[i][indices] * self._current_vols[i] for i in range(self.n_tracks)
        )
        np.clip(mixed, -1.0, 1.0, out=mixed)
        outdata[:] = mixed.reshape(outdata.shape)


# ── Example / quick test ────────────────────────────────────────────────────

if __name__ == "__main__":
    FILES = [
        "./audios/Audio_track_1.wav",  # base track — always on
        "./audios/Audio_track_2.wav",
        "./audios/Audio_track_3.wav",
        # "./audios/Audio_track_4.wav",
        # "./audios/Audio_track_5.wav",
        # "./audios/Audio_track_6.wav",
        # "./audios/Audio_track_7.wav",
        # "./audios/Audio_track_8.wav",
        # "./audios/Audio_track_9.wav",
    ]

    engine = RemixEngine(
        FILES,
        base_fg_vol=1.0,  # track 0 at full when alone
        base_bg_vol=0.20,  # track 0 dimmed when others are active
        track_fg_vol=0.90,  # triggered tracks at 90 %
        track_bg_vol=0.0,  # silent loops for tracks 1–8
        fade_in_duration=2.0,  # 2 s fade in
        fade_out_duration=3.0,  # 3 s fade out (slower feels more natural)
        solo_duration=5.0,  # 5 s in foreground before auto-exit
    )

    try:
        with engine:
            print("Playing. Type 1–8 + Enter to trigger a track, Ctrl-C to quit.")
            print("Multiple tracks can be active simultaneously.")
            while True:
                key = input().strip()
                if key.isdigit() and 1 <= int(key) <= 8:
                    idx = int(key)
                    print(f"→ Triggering track {idx + 1}")
                    engine.trigger(idx)
    except KeyboardInterrupt:
        print("\nStopped.")
