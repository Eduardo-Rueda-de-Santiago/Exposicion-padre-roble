import sqlite3
import os
from datetime import datetime
import threading

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data.db')

class DatabaseService:
    def __init__(self):
        self._connection_status = {
            'serial_connected': False,
            'last_reading_time': None,
            'readings_count': 0,
        }
        self._status_lock = threading.Lock()
        self.init_db()

    def init_db(self):
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sensor_id TEXT NOT NULL,
                value REAL NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        conn.commit()
        conn.close()

    def add_reading(self, sensor_id: str, value: float):
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO readings (sensor_id, value, timestamp) VALUES (?, ?, ?)',
            (sensor_id, value, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
        with self._status_lock:
            self._connection_status['serial_connected'] = True
            self._connection_status['last_reading_time'] = datetime.now().isoformat()
            self._connection_status['readings_count'] += 1

    def get_recent_readings(self, limit: int = 100, sensor_id: str = None):
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        cursor = conn.cursor()
        if sensor_id:
            cursor.execute(
                'SELECT sensor_id, value, timestamp FROM readings WHERE sensor_id=? ORDER BY timestamp DESC LIMIT ?',
                (sensor_id, limit)
            )
        else:
            cursor.execute(
                'SELECT sensor_id, value, timestamp FROM readings ORDER BY timestamp DESC LIMIT ?',
                (limit,)
            )
        rows = cursor.fetchall()
        conn.close()
        return [{'sensor_id': r[0], 'value': r[1], 'timestamp': r[2]} for r in reversed(rows)]

    def get_connection_status(self):
        with self._status_lock:
            return dict(self._connection_status)

    def get_all_sensors(self):
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('SELECT DISTINCT sensor_id FROM readings ORDER BY sensor_id')
        rows = cursor.fetchall()
        conn.close()
        return [r[0] for r in rows]

    def get_latest_reading(self, sensor_id: str):
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute(
            'SELECT sensor_id, value, timestamp FROM readings WHERE sensor_id=? ORDER BY timestamp DESC LIMIT 1',
            (sensor_id,)
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            return {'sensor_id': row[0], 'value': row[1], 'timestamp': row[2]}
        return None

db_service = DatabaseService()
