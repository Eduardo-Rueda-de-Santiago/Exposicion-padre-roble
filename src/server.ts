import createPort from "./utils/port";
import { ReadlineParser } from "@serialport/parser-readline";
import {
  handleEspError,
  handleEspLine,
} from "./controllers/port-input.controller";

const port = createPort();
const parser = port.pipe(new ReadlineParser({ delimiter: "\r\n" }));

port.on("open", () => {
  console.log(`Listening on ${port.conn} at ${port.baudRate} baud...`);
});

parser.on("data", handleEspLine);

port.on("error", handleEspError);
