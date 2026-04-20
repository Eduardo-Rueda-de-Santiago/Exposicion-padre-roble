from flask import Flask, jsonify, render_template
from flask_cors import CORS
from database import (
    init_db,
    get_recent_readings,
    get_connection_status,
    get_all_sensors,
    get_latest_reading,
)
from serial_reader import start_serial_reader
import threading
import os

app = Flask(__name__,
            template_folder='templates',
            static_folder='static')
CORS(app)

_serial_reader_thread = None

def start_serial():
    global _serial_reader_thread
    _serial_reader_thread = start_serial_reader()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status')
def status():
    conn_status = get_connection_status()
    sensors = get_all_sensors()
    latest = {s: get_latest_reading(s) for s in sensors}
    return jsonify({
        'serial_connected': conn_status['serial_connected'],
        'last_reading_time': conn_status['last_reading_time'],
        'readings_count': conn_status['readings_count'],
        'sensors': sensors,
        'latest': latest,
    })

@app.route('/api/sensors')
def sensors():
    return jsonify(get_all_sensors())

@app.route('/api/readings')
def readings():
    data = get_recent_readings(100)
    return jsonify(data)

@app.route('/api/readings/<sensor_id>')
def readings_by_sensor(sensor_id):
    data = get_recent_readings(100, sensor_id=sensor_id)
    return jsonify(data)

@app.route('/api/latest')
def latest():
    sensors = get_all_sensors()
    result = {}
    for s in sensors:
        reading = get_latest_reading(s)
        if reading:
            result[s] = reading
    return jsonify(result)

def start_web_server():
    init_db()
    start_serial()
    print("[WEB] Starting Flask server on http://0.0.0.0:5001")
    app.run(host='0.0.0.0', port=5001, debug=False, use_reloader=False, threaded=True)

if __name__ == '__main__':
    start_web_server()
