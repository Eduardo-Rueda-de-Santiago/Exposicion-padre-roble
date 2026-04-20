from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
from database import (
    init_db,
    get_recent_readings,
    get_connection_status,
    get_all_sensors,
    get_latest_reading,
)
from serial_reader import start_serial_reader
from video_player import get_manager
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
    vm = get_manager()
    return jsonify({
        'serial_connected': conn_status['serial_connected'],
        'last_reading_time': conn_status['last_reading_time'],
        'readings_count': conn_status['readings_count'],
        'sensors': sensors,
        'latest': latest,
        'video': vm.get_status(),
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

@app.route('/api/video/status')
def video_status():
    vm = get_manager()
    return jsonify(vm.get_status())

@app.route('/api/video/videos')
def video_list():
    vm = get_manager()
    return jsonify(vm.scan_videos())

@app.route('/api/video/play-all', methods=['POST'])
def video_play_all():
    vm = get_manager()
    data = request.get_json(silent=True) or {}
    videos = data.get('videos', [])
    vm.play_all(videos if videos else None)
    return jsonify({'status': 'playing'})

@app.route('/api/video/pause-all', methods=['POST'])
def video_pause_all():
    vm = get_manager()
    vm.pause_all()
    return jsonify({'status': 'paused'})

@app.route('/api/video/resume-all', methods=['POST'])
def video_resume_all():
    vm = get_manager()
    vm.resume_all()
    return jsonify({'status': 'playing'})

@app.route('/api/video/stop-all', methods=['POST'])
def video_stop_all():
    vm = get_manager()
    vm.stop_all()
    return jsonify({'status': 'stopped'})

@app.route('/api/video/screen/<int:screen_id>/play', methods=['POST'])
def video_play_screen(screen_id):
    vm = get_manager()
    data = request.get_json(silent=True) or {}
    vm.play_screen(screen_id, data.get('video'))
    return jsonify({'status': 'playing'})

@app.route('/api/video/screen/<int:screen_id>/pause', methods=['POST'])
def video_pause_screen(screen_id):
    vm = get_manager()
    vm.pause_screen(screen_id)
    return jsonify({'status': 'paused'})

@app.route('/api/video/screen/<int:screen_id>/resume', methods=['POST'])
def video_resume_screen(screen_id):
    vm = get_manager()
    vm.resume_screen(screen_id)
    return jsonify({'status': 'playing'})

@app.route('/api/video/screen/<int:screen_id>/stop', methods=['POST'])
def video_stop_screen(screen_id):
    vm = get_manager()
    vm.stop_screen(screen_id)
    return jsonify({'status': 'stopped'})

@app.route('/api/video/screen/<int:screen_id>/volume', methods=['POST'])
def video_volume_screen(screen_id):
    vm = get_manager()
    data = request.get_json(silent=True) or {}
    volume = data.get('volume', 100)
    vm.set_volume_screen(screen_id, volume)
    return jsonify({'volume': volume})

def start_web_server():
    init_db()
    start_serial()
    print("[WEB] Starting Flask server on http://0.0.0.0:5001")
    print("[VIDEO] Videos directory:", os.path.join(os.path.dirname(__file__), 'videos'))
    app.run(host='0.0.0.0', port=5001, debug=False, use_reloader=False, threaded=True)

if __name__ == '__main__':
    start_web_server()
