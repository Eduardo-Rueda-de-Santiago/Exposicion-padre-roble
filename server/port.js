import { SerialPort } from 'serialport';

const PORT = 'COM16';
const BAUD_RATE = 115200;


const port = new SerialPort({
    path: PORT,
    baudRate: BAUD_RATE,
});

port.conn = PORT

export default port;
