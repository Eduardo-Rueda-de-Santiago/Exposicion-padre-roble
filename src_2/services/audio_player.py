import threading
import time
import os
import json

import numpy as np
try:
    import sounddevice as sd
    import soundfile as sf
except ImportError:
    sd = None
    sf = None

class RemixEngine:
    def __init__(
        self,
        files: list[str],
        base_fg_vol: float = 1.0,
        base_bg_vol: float = 0.20,
        track_fg_vol: float = 0.90,
        track_bg_vol: float = 0.0,
        fade_in_duration: float = 2.0,
        fade_out_duration: float = 3.0,
        solo_duration: float = 5.0,
        device=None,
        blocksize: int = 1024,
    ):
        self.base_fg_vol = base_fg_vol
        self.base_bg_vol = base_bg_vol
        self.track_fg_vol = track_fg_vol
        self.track_bg_vol = track_bg_vol
        self.fade_in_duration = fade_in_duration
        self.fade_out_duration = fade_out_duration
        self.solo_duration = solo_duration
        self.device = device
        self.blocksize = blocksize
        self.data = []
        self.fs = None

        if not sf or not sd:
            print("[AudioService] sounddevice or soundfile not installed. Audio disabled.")
            self.n_tracks = 0
            return

        valid_files = [f for f in files if os.path.exists(f)]
        if not valid_files:
            print("[AudioService] No valid audio files found. Audio disabled.")
            self.n_tracks = 0
            return

        for path in valid_files:
            samples, fs = sf.read(path, always_2d=True)
            self.data.append(samples.astype(np.float32))
            if self.fs is None:
                self.fs = fs

        self.n_tracks = len(self.data)
        if self.n_tracks > 0:
            self.track_len = len(self.data[0])
            init_vols = np.array([base_fg_vol] + [track_bg_vol] * (self.n_tracks - 1), dtype=np.float64)
            self._current_vols = init_vols.copy()
            self._fade_from = init_vols.copy()
            self._fade_target = init_vols.copy()
            self._fade_pos = np.ones(self.n_tracks, dtype=np.float64)

        self._lock = threading.Lock()
        self._pending_targets = None
        self._active_tracks = set()
        self._solo_timers = {}
        self._start_frame = 0
        self._stream = None

    def trigger(self, track_idx: int) -> None:
        if not (0 < track_idx < self.n_tracks):
            return
        with self._lock:
            if track_idx in self._solo_timers:
                self._solo_timers[track_idx].cancel()
            self._active_tracks.add(track_idx)
            self._push_targets()
        timer = threading.Timer(self.solo_duration, self._deactivate, args=[track_idx])
        timer.daemon = True
        timer.start()
        with self._lock:
            self._solo_timers[track_idx] = timer

    def start(self):
        if self.n_tracks == 0 or not sd:
            return self
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
        if self.n_tracks == 0:
            return
        with self._lock:
            for timer in self._solo_timers.values():
                timer.cancel()
            self._solo_timers.clear()
            self._active_tracks.clear()
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *_):
        self.stop()

    def _deactivate(self, track_idx: int) -> None:
        with self._lock:
            self._active_tracks.discard(track_idx)
            self._solo_timers.pop(track_idx, None)
            self._push_targets()

    def _push_targets(self) -> None:
        targets = np.full(self.n_tracks, self.track_bg_vol, dtype=np.float64)
        targets[0] = self.base_bg_vol if self._active_tracks else self.base_fg_vol
        for i in self._active_tracks:
            targets[i] = self.track_fg_vol
        self._pending_targets = targets

    def _audio_callback(self, outdata, frames, time_info, status) -> None:
        with self._lock:
            new_targets = self._pending_targets
            self._pending_targets = None
        if new_targets is not None:
            changed = new_targets != self._fade_target
            self._fade_from[changed] = self._current_vols[changed]
            self._fade_pos[changed] = 0.0
            self._fade_target = new_targets
        fading_in = self._fade_target >= self._fade_from
        step = np.where(
            fading_in,
            frames / (self.fade_in_duration * self.fs),
            frames / (self.fade_out_duration * self.fs),
        )
        self._fade_pos = np.clip(self._fade_pos + step, 0.0, 1.0)
        t = self._fade_pos**2 * (3.0 - 2.0 * self._fade_pos)
        self._current_vols = self._fade_from + (self._fade_target - self._fade_from) * t
        indices = (np.arange(self._start_frame, self._start_frame + frames) % self.track_len)
        self._start_frame += frames
        mixed = sum(self.data[i][indices] * self._current_vols[i] for i in range(self.n_tracks))
        np.clip(mixed, -1.0, 1.0, out=mixed)
        outdata[:] = mixed.reshape(outdata.shape)

class AudioService:
    def __init__(self):
        # We start with empty files or default ones if they exist
        audios_dir = os.path.join(os.path.dirname(__file__), "..", "audios")
        config_path = os.path.join(os.path.dirname(__file__), "..", "config", "sensor_audio_map.json")
        
        self.sensor_to_track_idx = {}
        files = []
        
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
                
            bg_file = os.path.join(audios_dir, config.get("background_audio", ""))
            if os.path.exists(bg_file):
                files.append(bg_file)
            else:
                print(f"[AudioService] Warning: Background audio {bg_file} not found.")
                
            sensors = config.get("sensors", {})
            for sensor_id, data in sensors.items():
                audio_file = os.path.join(audios_dir, data.get("audio_file", ""))
                if os.path.exists(audio_file):
                    files.append(audio_file)
                    self.sensor_to_track_idx[sensor_id] = len(files) - 1
                else:
                    print(f"[AudioService] Warning: Audio file {audio_file} for {sensor_id} not found.")
                    
        except Exception as e:
            print(f"[AudioService] Error loading config: {e}")
        
        # If no files, we just disable audio
        self.engine = RemixEngine(
            files=files,
            base_fg_vol=1.0,
            base_bg_vol=0.20,
            track_fg_vol=0.90,
            track_bg_vol=0.0,
            fade_in_duration=2.0,
            fade_out_duration=3.0,
            solo_duration=5.0,
        )

    def start(self):
        self.engine.start()

    def stop(self):
        self.engine.stop()

    def trigger_sensor(self, sensor_id: str):
        if self.engine.n_tracks > 1:
            track_idx = self.sensor_to_track_idx.get(sensor_id)
            if track_idx is not None:
                self.engine.trigger(track_idx)

    def trigger_column(self, column_index: int):
        # Fallback for old code if needed
        sensor_id = f"ESP_COLUMN_{column_index}"
        self.trigger_sensor(sensor_id)

audio_service = AudioService()
