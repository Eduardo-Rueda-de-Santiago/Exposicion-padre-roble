import port from './port.js';
import { ReadlineParser } from '@serialport/parser-readline';
import audioPlayer from './audioPlayer.js';

const parser = port.pipe(new ReadlineParser({ delimiter: '\r\n' }));

port.on('open', () => {
    console.log(`Listening on ${port.conn} at ${port.baudRate} baud...`);
});

parser.on('data', (line) => {
    console.log(line);
    audioPlayer(line);
});

port.on('error', (err) => {
    console.error('Serial port error:', err.message);
});
