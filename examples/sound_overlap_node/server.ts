import { AudioContext } from "node-web-audio-api";
import fs from "fs";

const ctx = new AudioContext();

async function load(file: string) {
  const data = fs.readFileSync(file);
  return ctx.decodeAudioData(data.buffer as ArrayBuffer);
}

(async () => {
  const [audio1, audio2] = await Promise.all([
    load("audio1.mp3"),
    load("audio2.wav"),
  ]);

  const gain1 = ctx.createGain();
  gain1.gain.value = 0.5;

  const bg = ctx.createBufferSource();
  bg.buffer = audio1;
  bg.loop = true;
  bg.connect(gain1).connect(ctx.destination);
  bg.start();

  setInterval(() => {
    // smooth dim instead of abrupt cut
    gain1.gain.setTargetAtTime(0.2, ctx.currentTime, 0.2);

    const fx = ctx.createBufferSource();
    fx.buffer = audio2;
    fx.connect(ctx.destination);
    fx.start();

    fx.onended = () => {
      gain1.gain.setTargetAtTime(0.5, ctx.currentTime, 0.2);
    };
  }, 10000);
})();
