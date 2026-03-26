import wavPlayer from 'node-wav-player';


let audioPlaying = false;

function playAudio(audio) {
  console.log(audio);
  wavPlayer.play({ path: audio })
    .then(() => { audioPlaying = false; })
    .catch(err => { console.error(err); audioPlaying = false; });
}

export default function audioPlayer(line) {
  let match = line.match(/ESP_COLUMN_1-(-?\d+\.\d+)/);
  if (!match) return;
  let num = Number(match[1]);
  if (num === -1) return;
  if (num < 20 && !audioPlaying) {
    audioPlaying = true;
    playAudio("lyre.wav")
  }
  if (num > 20 && num < 40 && !audioPlaying) {
    audioPlaying = true;
    playAudio("guitar.wav")
  }
}


