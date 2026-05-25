"""
FarmLink Intelligence — Python Bridge Script
Phase 5.6 — Updated for Mark's website database schema

WHAT CHANGED FROM PREVIOUS VERSION:
  - Removed setup_database() — tables are created by create_tables.py
  - Removed farms seeding — farms are managed by the website admin
  - sync_status values match your ENUM: 'BUFFERED' or 'LIVE'
  - alerts table INSERT matches the new Alert model

BEFORE RUNNING:
  1. Run create_tables.py first to make sure all tables exist
  2. In your website admin, make sure a farm with
     hardware_farm_id = 'FARM-MARK-001' exists
  3. Update CONFIG below with your COM port and credentials

INSTALL DEPENDENCIES:
  pip install pyserial mysql-connector-python firebase-admin
"""

import serial
import json
import time
import logging
import sys
import signal
from datetime import datetime

import mysql.connector
from mysql.connector import Error as MySQLError

import firebase_admin
from firebase_admin import credentials, db as firebase_db

# ============================================================
# CONFIGURATION — UPDATE BEFORE RUNNING
# ============================================================
CONFIG = {
    "BLUETOOTH_PORT":     "COM5",           # <- CHANGE THIS
    "BLUETOOTH_BAUD":     9600,
    "MYSQL_HOST":         "localhost",
    "MYSQL_PORT":         3306,
    "MYSQL_USER":         "root",           # <- CHANGE THIS
    "MYSQL_PASSWORD":     "yourpassword",   # <- CHANGE THIS
    "MYSQL_DATABASE":     "farmlink",       # <- match your .env DATABASE_URL
    "FIREBASE_CRED_PATH": "serviceAccountKey.json",
    "FIREBASE_DB_URL":    "https://farmlink-intelligence-xxxxx-default-rtdb.firebaseio.com",
    "JSON_START":         ">>>JSON_START<<<",
    "JSON_END":           ">>>JSON_END<<<",
    "HEAT_THRESHOLD":     35.0,
    "CRITICAL_SOIL":      20.0,
    "IRRIGATE_THRESHOLD": 30.0,
}

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("farmlink_bridge.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("FarmLink")

_mysql_conn     = None
_firebase_ready = False
_running        = True
_stats = {
    "readings_received": 0,
    "mysql_inserts":     0,
    "mysql_duplicates":  0,
    "firebase_syncs":    0,
    "parse_errors":      0,
    "alerts_logged":     0,
}

def handle_shutdown(sig, frame):
    global _running
    log.info("Shutdown signal received.")
    _running = False

signal.signal(signal.SIGINT,  handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)

# ============================================================
# MYSQL — CONNECT
# ============================================================
def connect_mysql():
    global _mysql_conn
    while _running:
        try:
            conn = mysql.connector.connect(
                host     = CONFIG["MYSQL_HOST"],
                port     = CONFIG["MYSQL_PORT"],
                user     = CONFIG["MYSQL_USER"],
                password = CONFIG["MYSQL_PASSWORD"],
                database = CONFIG["MYSQL_DATABASE"],
            )
            if conn.is_connected():
                log.info("MySQL connected — database: %s", CONFIG["MYSQL_DATABASE"])
                _mysql_conn = conn
                return conn
        except MySQLError as e:
            log.error("MySQL connection failed: %s. Retrying in 5s...", e)
            time.sleep(5)
    return None

# ============================================================
# MYSQL — INSERT READING
#
# Uses INSERT IGNORE — if the same reading_id arrives twice,
# MySQL silently skips it. No duplicate rows ever.
#
# sync_status must be 'BUFFERED' or 'LIVE' — both are valid
# values in your ENUM('BUFFERED','LIVE','SYNCED') column.
# ============================================================
INSERT_SQL = """
INSERT IGNORE INTO sensor_readings
    (reading_id, farm_id, recorded_at, temperature, humidity,
     soil_moisture, is_raining, rain_intensity,
     heat_stress_flag, irrigation_active, sync_status)
VALUES
    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

def insert_reading(conn, data):
    cursor = conn.cursor()
    try:
        try:
            recorded_at = datetime.fromisoformat(data["recorded_at"])
        except (ValueError, KeyError):
            recorded_at = datetime.now()
            log.warning("Could not parse recorded_at — using current time.")

        # sync_status from Arduino is 'BUFFERED' or 'LIVE'
        # Both are valid ENUM values in your schema
        sync = data.get("sync_status", "BUFFERED")
        if sync not in ("BUFFERED", "LIVE", "SYNCED"):
            sync = "BUFFERED"

        values = (
            data.get("reading_id"),
            data.get("farm_id", "FARM-MARK-001"),
            recorded_at,
            data.get("temperature"),
            data.get("humidity"),
            data.get("soil_moisture"),
            1 if data.get("is_raining") else 0,
            data.get("rain_intensity", 0),
            1 if data.get("heat_stress_flag") else 0,
            1 if data.get("irrigation_active") else 0,
            sync,
        )

        cursor.execute(INSERT_SQL, values)
        conn.commit()

        if cursor.rowcount > 0:
            _stats["mysql_inserts"] += 1
            log.info(
                "MySQL INSERT OK — %s | T:%.1f C  H:%.1f%%  Soil:%.1f%%  [%s]",
                data.get("reading_id"),
                data.get("temperature", 0),
                data.get("humidity", 0),
                data.get("soil_moisture", 0),
                sync,
            )
            return True
        else:
            _stats["mysql_duplicates"] += 1
            log.info("MySQL DUPLICATE skipped — %s", data.get("reading_id"))
            return False

    except MySQLError as e:
        log.error("MySQL INSERT failed: %s", e)
        conn.rollback()
        return False
    finally:
        cursor.close()

# ============================================================
# MYSQL — INSERT ALERT
# Matches your new Alert model exactly.
# ============================================================
ALERT_SQL = """
INSERT INTO alerts (reading_id, farm_id, alert_type, alert_value)
VALUES (%s, %s, %s, %s)
"""

def insert_alert(conn, reading_id, farm_id, alert_type, alert_value):
    cursor = conn.cursor()
    try:
        cursor.execute(ALERT_SQL, (reading_id, farm_id, alert_type, alert_value))
        conn.commit()
        _stats["alerts_logged"] += 1
        log.warning("ALERT — %s: %.2f (reading: %s)", alert_type, alert_value, reading_id)
    except MySQLError as e:
        log.error("Alert INSERT failed: %s", e)
        conn.rollback()
    finally:
        cursor.close()

# ============================================================
# ALERT DETECTION
# ============================================================
def check_and_log_alerts(conn, data):
    rid     = data.get("reading_id")
    fid     = data.get("farm_id", "FARM-MARK-001")
    temp    = data.get("temperature",   0)
    soil    = data.get("soil_moisture", 0)
    raining = data.get("is_raining",    False)

    if temp and temp > CONFIG["HEAT_THRESHOLD"]:
        insert_alert(conn, rid, fid, "HEAT_STRESS", temp)

    if soil is not None and soil < CONFIG["CRITICAL_SOIL"]:
        insert_alert(conn, rid, fid, "CRITICAL_DROUGHT", soil)
    elif soil is not None and soil < CONFIG["IRRIGATE_THRESHOLD"] and not raining:
        insert_alert(conn, rid, fid, "IRRIGATION_TRIGGER", soil)

# ============================================================
# FIREBASE — INITIALISE
# ============================================================
def init_firebase():
    global _firebase_ready
    try:
        cred = credentials.Certificate(CONFIG["FIREBASE_CRED_PATH"])
        firebase_admin.initialize_app(cred, {"databaseURL": CONFIG["FIREBASE_DB_URL"]})
        _firebase_ready = True
        log.info("Firebase connected.")
        return True
    except Exception as e:
        log.warning("Firebase init failed: %s — continuing with MySQL only.", e)
        _firebase_ready = False
        return False

# ============================================================
# FIREBASE — SYNC READING
# ============================================================
def sync_to_firebase(data):
    if not _firebase_ready:
        return False
    try:
        reading_id = data.get("reading_id")
        if not reading_id:
            return False
        firebase_db.reference(f"/sensor_readings/{reading_id}").set(data)
        _stats["firebase_syncs"] += 1
        log.info("Firebase SYNC OK — %s", reading_id)
        return True
    except Exception as e:
        log.error("Firebase sync failed: %s", e)
        return False

# ============================================================
# JSON EXTRACTION FROM SERIAL STREAM
# ============================================================
def extract_json_from_serial(serial_port):
    buffer     = []
    collecting = False

    while _running:
        try:
            raw = serial_port.readline()
            if not raw:
                continue
            try:
                line = raw.decode("utf-8", errors="ignore").strip()
            except Exception:
                continue
            if not line:
                continue

            if CONFIG["JSON_START"] in line:
                buffer     = []
                collecting = True
                continue

            if CONFIG["JSON_END"] in line:
                if collecting and buffer:
                    json_str = "\n".join(buffer)
                    try:
                        data = json.loads(json_str)
                        _stats["readings_received"] += 1
                        yield data
                    except json.JSONDecodeError as e:
                        _stats["parse_errors"] += 1
                        log.error("JSON parse error: %s", e)
                collecting = False
                buffer     = []
                continue

            if collecting:
                buffer.append(line)

        except serial.SerialException as e:
            log.error("Serial read error: %s", e)
            time.sleep(1)

# ============================================================
# BLUETOOTH — CONNECT
# ============================================================
def connect_bluetooth():
    while _running:
        try:
            port = serial.Serial(
                port     = CONFIG["BLUETOOTH_PORT"],
                baudrate = CONFIG["BLUETOOTH_BAUD"],
                timeout  = 2,
            )
            log.info("Bluetooth connected — %s @ %d baud",
                     CONFIG["BLUETOOTH_PORT"], CONFIG["BLUETOOTH_BAUD"])
            return port
        except serial.SerialException as e:
            log.error("Cannot open %s: %s. Retrying in 5s...",
                      CONFIG["BLUETOOTH_PORT"], e)
            time.sleep(5)
    return None

# ============================================================
# MYSQL — RECONNECT IF DROPPED
# ============================================================
def ensure_mysql(conn):
    try:
        if conn and conn.is_connected():
            return conn
    except MySQLError:
        pass
    log.warning("MySQL connection lost. Reconnecting...")
    return connect_mysql()

# ============================================================
# STATS PRINTER
# ============================================================
def print_stats():
    log.info(
        "Stats — Received:%d  MySQL:%d  Dupes:%d  Firebase:%d  Alerts:%d  Errors:%d",
        _stats["readings_received"], _stats["mysql_inserts"],
        _stats["mysql_duplicates"], _stats["firebase_syncs"],
        _stats["alerts_logged"],    _stats["parse_errors"],
    )

# ============================================================
# MAIN
# ============================================================
def main():
    log.info("=" * 55)
    log.info("FarmLink Intelligence — Python Bridge v5.6")
    log.info("=" * 55)

    # Step 1: Connect MySQL
    mysql_conn = connect_mysql()
    if not mysql_conn:
        log.error("Could not connect to MySQL. Exiting.")
        sys.exit(1)

    # Step 2: Verify the alerts table exists
    # (all other tables are managed by create_tables.py)
    try:
        cursor = mysql_conn.cursor()
        cursor.execute("SELECT 1 FROM alerts LIMIT 1;")
        cursor.fetchall()
        cursor.close()
        log.info("alerts table verified.")
    except MySQLError:
        log.error(
            "The 'alerts' table does not exist.\n"
            "  Add the Alert model to models.py and run:\n"
            "  python scripts/create_tables.py"
        )
        sys.exit(1)

    # Step 3: Connect Firebase
    init_firebase()

    # Step 4: Connect Bluetooth
    bt_port = connect_bluetooth()
    if not bt_port:
        log.error("Could not open Bluetooth port. Exiting.")
        sys.exit(1)

    log.info("Listening for sensor readings... (Ctrl+C to stop)")
    log.info("-" * 55)

    readings_since_stats = 0

    for reading in extract_json_from_serial(bt_port):
        mysql_conn = ensure_mysql(mysql_conn)
        if not mysql_conn:
            log.error("MySQL unavailable. Skipping reading.")
            continue

        inserted = insert_reading(mysql_conn, reading)

        if inserted:
            check_and_log_alerts(mysql_conn, reading)

        sync_to_firebase(reading)

        readings_since_stats += 1
        if readings_since_stats >= 10:
            print_stats()
            readings_since_stats = 0

    # Shutdown
    log.info("-" * 55)
    log.info("Bridge stopped.")
    print_stats()

    if bt_port and bt_port.is_open:
        bt_port.close()
    if mysql_conn and mysql_conn.is_connected():
        mysql_conn.close()


if __name__ == "__main__":
    main()