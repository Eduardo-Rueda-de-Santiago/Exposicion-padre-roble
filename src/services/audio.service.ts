import { AudioContext } from "node-web-audio-api";
import fs from "node:fs/promises";
import path from "node:path";

/**
 * Global audio context (singleton for the app)
 */
const AUDIO_CONTEXT = new AudioContext();

/**
 * Base audio directories
 */
const AUDIO_DIR = path.join(__dirname, "..", "audios");
const AUDIO_BACKGROUNDS_DIR = path.join(AUDIO_DIR, "backgrounds");
const AUDIO_EFFECTS_DIR = path.join(AUDIO_DIR, "effects");

/**
 * Supported audio file extensions
 */
const SUPPORTED_EXTENSIONS = [".mp3", ".wav", ".ogg"];

/**
 * Currently playing background audio (for control/dimming)
 */
let currentBackgroundSource: AudioBufferSourceNode | null = null;
let currentBackgroundGain: GainNode | null = null;

/**
 * Utility: filter only valid audio files
 */
function isAudioFile(file: string): boolean {
  return SUPPORTED_EXTENSIONS.includes(path.extname(file).toLowerCase());
}

/**
 * Utility: read and decode an audio file into a buffer
 */
async function loadAudioBuffer(filePath: string): Promise<AudioBuffer> {
  const file = await fs.readFile(filePath);
  const arrayBuffer = file.buffer.slice(
    file.byteOffset,
    file.byteOffset + file.byteLength,
  );

  return AUDIO_CONTEXT.decodeAudioData(arrayBuffer);
}

/**
 * Lists available background audio files
 */
export async function listAudioBackgrounds(): Promise<string[]> {
  try {
    const entries = await fs.readdir(AUDIO_BACKGROUNDS_DIR, {
      withFileTypes: true,
    });

    return entries
      .filter((e) => e.isFile() && isAudioFile(e.name))
      .map((e) => e.name);
  } catch (e) {
    console.error("Failed to list background audios:", e);
    return [];
  }
}

/**
 * Lists available audio effects
 */
export async function listAudioEffects(): Promise<string[]> {
  try {
    const entries = await fs.readdir(AUDIO_EFFECTS_DIR, {
      withFileTypes: true,
    });

    return entries
      .filter((e) => e.isFile() && isAudioFile(e.name))
      .map((e) => e.name);
  } catch (e) {
    console.error("Failed to list audio effects:", e);
    return [];
  }
}

/**
 * Plays a looping background audio track.
 * Stops any currently playing background and replaces it.
 */
export async function playBackgroundAudio(audioName: string): Promise<void> {
  const filePath = path.join(AUDIO_BACKGROUNDS_DIR, audioName);

  // Ensure audio context is running
  if (AUDIO_CONTEXT.state !== "running") {
    await AUDIO_CONTEXT.resume();
  }

  // Stop existing background cleanly
  if (currentBackgroundSource) {
    try {
      currentBackgroundSource.stop();
    } catch {}
    currentBackgroundSource.disconnect();
    currentBackgroundSource = null;
  }

  if (currentBackgroundGain) {
    currentBackgroundGain.disconnect();
    currentBackgroundGain = null;
  }

  const buffer = await loadAudioBuffer(filePath);

  const source = AUDIO_CONTEXT.createBufferSource();
  source.buffer = buffer;

  // 🔁 THIS is what makes it loop forever
  source.loop = true;

  const gainNode = AUDIO_CONTEXT.createGain();
  gainNode.gain.value = 1;

  source.connect(gainNode).connect(AUDIO_CONTEXT.destination);

  source.start(0);

  // Track current background
  currentBackgroundSource = source;
  currentBackgroundGain = gainNode;

  // Safety cleanup (in case it's ever stopped externally)
  source.onended = () => {
    if (currentBackgroundSource === source) {
      currentBackgroundSource = null;
      currentBackgroundGain = null;
    }
  };
}

/**
 * Plays an effect sound while temporarily lowering background volume.
 */
export async function playEffectAudio(audioName: string): Promise<void> {
  const filePath = path.join(AUDIO_EFFECTS_DIR, audioName);

  const buffer = await loadAudioBuffer(filePath);

  const source = AUDIO_CONTEXT.createBufferSource();
  source.buffer = buffer;

  const gainNode = AUDIO_CONTEXT.createGain();
  gainNode.gain.value = 1;

  source.connect(gainNode).connect(AUDIO_CONTEXT.destination);

  // Dim background if exists
  if (currentBackgroundGain) {
    currentBackgroundGain.gain.setValueAtTime(
      currentBackgroundGain.gain.value,
      AUDIO_CONTEXT.currentTime,
    );

    currentBackgroundGain.gain.linearRampToValueAtTime(
      0.3,
      AUDIO_CONTEXT.currentTime + 0.2,
    );
  }

  source.start();

  // Restore volume after effect finishes
  source.onended = () => {
    if (currentBackgroundGain) {
      currentBackgroundGain.gain.setValueAtTime(
        currentBackgroundGain.gain.value,
        AUDIO_CONTEXT.currentTime,
      );

      currentBackgroundGain.gain.linearRampToValueAtTime(
        1,
        AUDIO_CONTEXT.currentTime + 0.3,
      );
    }
  };
}
/**
 * Stops the currently playing background audio.
 *
 * @param fadeOutMs - Optional fade-out duration in milliseconds (default: 300ms)
 */
export function stopBackgroundAudio(fadeOutMs: number = 300): void {
  if (!currentBackgroundSource || !currentBackgroundGain) {
    return;
  }

  const now = AUDIO_CONTEXT.currentTime;
  const fadeOutSeconds = fadeOutMs / 1000;

  try {
    // Smooth fade out
    currentBackgroundGain.gain.setValueAtTime(
      currentBackgroundGain.gain.value,
      now,
    );

    currentBackgroundGain.gain.linearRampToValueAtTime(0, now + fadeOutSeconds);

    // Stop after fade completes
    currentBackgroundSource.stop(now + fadeOutSeconds);
  } catch (err) {
    console.warn("Error stopping background audio:", err);
    // Fallback: immediate stop
    currentBackgroundSource.stop();
  }

  // Cleanup after stop
  currentBackgroundSource.onended = () => {
    currentBackgroundSource?.disconnect();
    currentBackgroundGain?.disconnect();

    currentBackgroundSource = null;
    currentBackgroundGain = null;
  };
}
