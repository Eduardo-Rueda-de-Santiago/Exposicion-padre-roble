import { SerialPort, SerialPortOpenOptions } from "serialport";

/**
 * Default serial port path.
 * Change this depending on your OS:
 * - Windows: COMx (e.g., COM16)
 * - Linux/macOS: /dev/ttyUSB0, /dev/tty.usbserial, etc.
 */
export const DEFAULT_PORT_PATH = "COM16";

/**
 * Default baud rate for the serial connection.
 */
export const DEFAULT_BAUD_RATE = 115200;

/**
 * Extended SerialPort type to include custom metadata.
 */
export interface ExtendedSerialPort extends SerialPort {
  /**
   * Stores the connection path used to initialize the port.
   */
  conn?: string;
}

/**
 * Creates and returns a configured SerialPort instance.
 *
 * @param path - The serial port path (e.g., "COM16" or "/dev/ttyUSB0")
 * @param baudRate - Communication speed in bits per second
 * @returns Configured SerialPort instance
 *
 * @example
 * ```ts
 * const port = createPort();
 * const customPort = createPort("COM3", 9600);
 * ```
 */
export default function createPort(
  path: string = DEFAULT_PORT_PATH,
  baudRate: number = DEFAULT_BAUD_RATE,
): ExtendedSerialPort {
  const options: SerialPortOpenOptions<SerialPort> = {
    path,
    baudRate,
  };

  const port = new SerialPort(options) as ExtendedSerialPort;

  // Attach metadata safely
  port.conn = path;

  return port;
}
