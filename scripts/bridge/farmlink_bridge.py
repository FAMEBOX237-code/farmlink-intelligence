"""
FarmLink Intelligence — Python Bridge
Phase 5.6 — Revised for website database schema

WHAT THIS SCRIPT DOES:
  1. Connects to HC-06 Bluetooth (COM port on your laptop)
  2. Reads JSON packets between >>>JSON_START<<< and >>>JSON_END<<<
  3. Translates hardware_farm_id string → integer farms.id (cached)
  4. Inserts reading into sensor_readings (INSERT IGNORE on reading_id)
  5. Logs alert events to alerts table
  6. Syncs reading to Firebase

KEY SCHEMA FACTS THIS BRIDGE RESPECTS:
  sensor_readings.id        — INTEGER AUTO PK  (bridge never sets this)
  sensor_readings.reading_id — VARCHAR(36) UNIQUE  (bridge idempotency key)
  sensor_readings.farm_id   — INTEGER FK → farms.id  (bridge looks this up)
  sensor_readings.light_intensity — nullable, bridge sends NULL (Arduino omits it)
  alerts.farm_id            — INTEGER, no FK constraint
  alerts.reading_id         — VARCHAR(36), no FK constraint

THE ARDUINO .INO DOES NOT CHANGE:
  Arduino sends farm_id as "FARM-MARK-001" (the hardware string).
  This bridge translates it to the integer farms.id before inserting.
  Arduino never knows or needs the database integer.

BEFORE RUNNING:
  1. python scripts/create_tables.py  (tables must exist first)
  2. In website admin: create a farm with hardware_farm_id = FARM-MARK-001
  3. Update CONFIG below — especially BLUETOOTH_PORT and MYSQL_PASSWORD
  4. python farmlink_bridge.py

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
    # ── Bluetooth serial ─────────────────────────────────────
    # Windows: "COM5"  |  Mac/Linux: "/dev/tty.HC-06-DevB"
    "BLUETOOTH_PORT":   "COM5",           # <- CHANGE THIS
    "BLUETOOTH_BAUD":   9600,

    # ── MySQL ────────────────────────────────────────────────
    "MYSQL_HOST":       "localhost",
    "MYSQL_PORT":       3306,
    "MYSQL_USER":       "root",           # <- CHANGE IF DIFFERENT
    "MYSQL_PASSWORD":   "yourpassword",   # <- CHANGE THIS
    "MYSQL_DATABASE":   "farmlink",       # <- match your .env DATABASE_URL

    # ── Firebase ─────────────────────────────────────────────
    # Download service account key from:
    # Firebase Console → Project Settings → Service Accounts → Generate new key
    "FIREBASE_CRED_PATH": "serviceAccountKey.json",
    "FIREBASE_DB_URL":    "https://farmlink-intelligence-xxxxx-default-rtdb.firebaseio.com",

    # ── JSON markers (must match Arduino #define exactly) ────
    "JSON_START": ">>>JSON_START<<<",
    "JSON_END":   ">>>JSON_END<<<",

    # ── Alert thresholds (must match Arduino thresholds) ─────
    "HEAT_THRESHOLD":     35.0,   # Celsius
    "CRITICAL_SOIL":      20.0,   # % moisture
    "IRRIGATE_THRESHOLD": 30.0,   # % moisture

    # ── Hardware farm identity ────────────────────────────────
    # This is the string burned into the Arduino sketch (#define FARM_ID).
    # The bridge uses it to look up the integer farms.id in the database.
    "HARDWARE_FARM_ID": "FARM-MARK-001",
}

# ============================================================
# LOGGING
# Prints to terminal AND saves to farmlink_bridge.log
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

# ============================================================
# GLOBAL STATE
# ============================================================
_mysql_conn     = None
_firebase_ready = False
_running        = True

# Cache: hardware_farm_id string → integer farms.id
# Avoids querying MySQL on every reading.
# For a demo with one farm this is a single-entry dict.
_farm_id_cache  = {}

_stats = {
    "readings_received": 0,
    "mysql_inserts":     0,
    "mysql_duplicates":  0,
    "firebase_syncs":    0,
    "parse_errors":      0,
    "alerts_logged":     0,
}

# ============================================================
# SIGNAL HANDLER — Ctrl+C closes cleanly
# ============================================================
def handle_shutdown(sig, frame):
    global _running
    log.info("Shutdown signal received. Closing...")
    _running = False

signal.signal(signal.SIGINT,  handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)

# ============================================================
# MYSQL — CONNECT
# ============================================================
def connect_mysql():
    """Opens MySQL connection. Retries every 5s until success."""
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
# FARM ID LOOKUP (with cache)
#
# TEACHING MOMENT — why is this needed?
#
# The Arduino has "FARM-MARK-001" hardcoded in its sketch.
# Every JSON it sends includes:  "farm_id": "FARM-MARK-001"
#
# But your website database uses sensor_readings.farm_id as an
# INTEGER FK → farms.id. The website team built it this way so
# all their queries use the same integer PK as everything else.
#
# This function bridges that gap:
#   "FARM-MARK-001"  →  looks up farms WHERE hardware_farm_id = ?
#                    →  returns farms.id integer (e.g. 1)
#
# The result is cached in _farm_id_cache so MySQL is only
# queried ONCE per bridge session, not once per reading.
# At 1 reading per 4 seconds over 8 hours = 7,200 readings saved.
#
# Returns None if the farm is not found — the bridge will
# refuse to insert and print a clear error explaining what
# to do (create the farm in the website admin panel).
# ============================================================
def lookup_farm_id(conn, hardware_farm_id):
    # Return from cache if already looked up this session
    if hardware_farm_id in _farm_id_cache:
        return _farm_id_cache[hardware_farm_id]

    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT id FROM farms WHERE hardware_farm_id = %s LIMIT 1",
            (hardware_farm_id,)
        )
        row = cursor.fetchone()
        if row:
            farm_int_id = row[0]
            _farm_id_cache[hardware_farm_id] = farm_int_id
            log.info(
                "Farm resolved: hardware_farm_id='%s' → farms.id=%d",
                hardware_farm_id, farm_int_id
            )
            return farm_int_id
        else:
            log.error(
                "Farm not found: hardware_farm_id='%s'\n"
                "  Fix: In your website admin panel, open the farm\n"
                "       that this sensor belongs to and set its\n"
                "       hardware_farm_id field to '%s'\n"
                "       Then restart the bridge.",
                hardware_farm_id, hardware_farm_id
            )
            return None
    except MySQLError as e:
        log.error("Farm lookup query failed: %s", e)
        return None
    finally:
        cursor.close()

# ============================================================
# MYSQL — INSERT READING
#
# Column mapping (current schema):
#   reading_id      VARCHAR(36) UNIQUE   Arduino-generated ID
#   farm_id         INTEGER FK           from lookup_farm_id()
#   recorded_at     DATETIME             from Arduino DS1302 RTC
#   temperature     DECIMAL(5,2)
#   humidity        DECIMAL(5,2)
#   soil_moisture   DECIMAL(5,2)         Arduino sends 1dp, MySQL stores 2dp fine
#   light_intensity DECIMAL(8,2) NULL    Arduino doesn't send this — always NULL
#   is_raining      TINYINT(1)
#   rain_intensity  INT
#   heat_stress_flag  TINYINT(1)
#   irrigation_active TINYINT(1)
#   sync_status     ENUM                 'BUFFERED' or 'LIVE'
#
# Columns NOT in INSERT (MySQL handles them automatically):
#   id              — AUTO_INCREMENT PK
#   inserted_at     — DEFAULT CURRENT_TIMESTAMP
#   quality_score   — written by the calculate_quality_score trigger
#
# INSERT IGNORE — if reading_id already exists (UNIQUE constraint),
# MySQL silently skips the row. No error, no duplicate.
# This is the idempotency guarantee.
# ============================================================
INSERT_SQL = """
INSERT IGNORE INTO sensor_readings
    (reading_id, farm_id, recorded_at,
     temperature, humidity, soil_moisture, light_intensity,
     is_raining, rain_intensity,
     heat_stress_flag, irrigation_active,
     sync_status)
VALUES
    (%s, %s, %s,
     %s, %s, %s, %s,
     %s, %s,
     %s, %s,
     %s)
"""

def insert_reading(conn, data, farm_int_id):
    """
    Inserts one reading into sensor_readings.
    farm_int_id  — the integer farms.id (looked up before calling this)
    Returns True if a new row was inserted, False if duplicate or error.
    """
    cursor = conn.cursor()
    try:
        # Parse the recorded_at timestamp from Arduino ISO format
        # Arduino sends: "2026-04-24T10:23:15"
        try:
            recorded_at = datetime.fromisoformat(data["recorded_at"])
        except (ValueError, KeyError):
            recorded_at = datetime.now()
            log.warning("recorded_at missing or invalid — using current time.")

        # Validate sync_status against the ENUM values in the schema
        sync = data.get("sync_status", "BUFFERED")
        if sync not in ("BUFFERED", "LIVE", "SYNCED"):
            sync = "BUFFERED"

        values = (
            data.get("reading_id"),               # VARCHAR(36) UNIQUE
            farm_int_id,                           # INTEGER — from lookup
            recorded_at,                           # DATETIME
            data.get("temperature"),               # DECIMAL(5,2)
            data.get("humidity"),                  # DECIMAL(5,2)
            data.get("soil_moisture"),             # DECIMAL(5,2)
            None,                                  # light_intensity — Arduino omits, always NULL
            1 if data.get("is_raining") else 0,   # TINYINT(1)
            data.get("rain_intensity", 0),         # INT
            1 if data.get("heat_stress_flag") else 0,   # TINYINT(1)
            1 if data.get("irrigation_active") else 0,  # TINYINT(1)
            sync,                                  # ENUM
        )

        cursor.execute(INSERT_SQL, values)
        conn.commit()

        if cursor.rowcount > 0:
            _stats["mysql_inserts"] += 1
            log.info(
                "MySQL INSERT OK — %s | T:%.1fC  H:%.1f%%  Soil:%.1f%%  [%s]",
                data.get("reading_id", "?"),
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
#
# alerts schema (current):
#   alert_id     INTEGER AUTO_INCREMENT PK
#   reading_id   VARCHAR(36)  — plain string, no FK constraint
#   farm_id      INTEGER      — plain integer, no FK constraint
#   alert_type   VARCHAR(50)
#   alert_value  DECIMAL(8,2)
#   triggered_at DATETIME     — MySQL DEFAULT
#
# Both reading_id and farm_id have no FK constraints in the
# current schema. This means alert history is permanent —
# deleting a reading or a farm never wipes out alerts.
# ============================================================
ALERT_SQL = """
INSERT INTO alerts (reading_id, farm_id, alert_type, alert_value)
VALUES (%s, %s, %s, %s)
"""

def insert_alert(conn, reading_id, farm_int_id, alert_type, alert_value):
    """
    Logs one alert event.
    reading_id   — the reading_id string (e.g. "FL-0047-20260424-102315")
    farm_int_id  — integer farms.id (not the hardware string)
    """
    cursor = conn.cursor()
    try:
        cursor.execute(ALERT_SQL, (reading_id, farm_int_id, alert_type, alert_value))
        conn.commit()
        _stats["alerts_logged"] += 1
        log.warning(
            "ALERT LOGGED — type=%s  value=%.2f  reading=%s  farm_id=%d",
            alert_type, alert_value, reading_id, farm_int_id
        )
    except MySQLError as e:
        log.error("Alert INSERT failed: %s", e)
        conn.rollback()
    finally:
        cursor.close()

# ============================================================
# ALERT DETECTION
# Mirrors the thresholds defined in the Arduino sketch.
# farm_int_id is the INTEGER farms.id — not the hardware string.
# ============================================================
def check_and_log_alerts(conn, data, farm_int_id):
    rid     = data.get("reading_id")
    temp    = data.get("temperature",   0)
    soil    = data.get("soil_moisture", 0)
    raining = data.get("is_raining",    False)

    # Heat stress
    if temp and temp > CONFIG["HEAT_THRESHOLD"]:
        insert_alert(conn, rid, farm_int_id, "HEAT_STRESS", temp)

    # Critical drought (soil very low)
    if soil is not None and soil < CONFIG["CRITICAL_SOIL"]:
        insert_alert(conn, rid, farm_int_id, "CRITICAL_DROUGHT", soil)

    # Irrigation trigger (soil low, no rain — pump should activate)
    elif soil is not None and soil < CONFIG["IRRIGATE_THRESHOLD"] and not raining:
        insert_alert(conn, rid, farm_int_id, "IRRIGATION_TRIGGER", soil)

# ============================================================
# FIREBASE — INITIALISE
# ============================================================
def init_firebase():
    """
    Initialises the Firebase Admin SDK using the service account
    JSON downloaded from Firebase Console.
    Non-fatal — if Firebase is unavailable, MySQL still works.
    """
    global _firebase_ready
    try:
        cred = credentials.Certificate(CONFIG["FIREBASE_CRED_PATH"])
        firebase_admin.initialize_app(cred, {
            "databaseURL": CONFIG["FIREBASE_DB_URL"]
        })
        _firebase_ready = True
        log.info("Firebase connected — %s", CONFIG["FIREBASE_DB_URL"])
        return True
    except Exception as e:
        log.warning(
            "Firebase init failed: %s\n"
            "  Readings will still go to MySQL. Firebase sync disabled.",
            e
        )
        _firebase_ready = False
        return False

# ============================================================
# FIREBASE — SYNC ONE READING
# ============================================================
def sync_to_firebase(data):
    """
    Pushes the full JSON reading to Firebase under
    /sensor_readings/{reading_id}
    Firebase set() is idempotent — sending the same reading_id
    twice just overwrites with identical data. No duplicates.
    """
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
# JSON EXTRACTION FROM BLUETOOTH SERIAL STREAM
#
# The Arduino wraps every JSON payload with markers:
#   >>>JSON_START<<<
#   { ...multi-line JSON... }
#   >>>JSON_END<<<
#
# This generator collects lines between the markers and
# yields one parsed dict per complete JSON object.
# It handles partial packets, noise bytes, and fragmentation.
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

            # Start marker — begin collecting
            if CONFIG["JSON_START"] in line:
                buffer     = []
                collecting = True
                continue

            # End marker — parse what we collected
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
                        log.debug("Bad JSON:\n%s", json_str)
                collecting = False
                buffer     = []
                continue

            # Middle of a JSON packet — collect the line
            if collecting:
                buffer.append(line)

        except serial.SerialException as e:
            log.error("Serial read error: %s", e)
            time.sleep(1)
        except Exception as e:
            log.error("Unexpected error in serial reader: %s", e)
            time.sleep(1)

# ============================================================
# BLUETOOTH SERIAL — CONNECT
# ============================================================
def connect_bluetooth():
    """Opens the HC-06 Bluetooth COM port. Retries every 5s."""
    while _running:
        try:
            port = serial.Serial(
                port     = CONFIG["BLUETOOTH_PORT"],
                baudrate = CONFIG["BLUETOOTH_BAUD"],
                timeout  = 2,
            )
            log.info(
                "Bluetooth connected — %s @ %d baud",
                CONFIG["BLUETOOTH_PORT"], CONFIG["BLUETOOTH_BAUD"]
            )
            return port
        except serial.SerialException as e:
            log.error(
                "Cannot open %s: %s\n"
                "  → Pair HC-06 via Bluetooth settings first.\n"
                "  → Check BLUETOOTH_PORT in CONFIG.\n"
                "  Retrying in 5s...",
                CONFIG["BLUETOOTH_PORT"], e
            )
            time.sleep(5)
    return None

# ============================================================
# MYSQL — RECONNECT IF DROPPED
# ============================================================
def ensure_mysql(conn):
    """Checks if MySQL is still alive. Reconnects if not."""
    try:
        if conn and conn.is_connected():
            return conn
    except MySQLError:
        pass
    log.warning("MySQL connection dropped. Reconnecting...")
    return connect_mysql()

# ============================================================
# STATS PRINTER — every 10 readings
# ============================================================
def print_stats():
    log.info(
        "── Stats ── Received:%d  MySQL:%d  Dupes:%d  "
        "Firebase:%d  Alerts:%d  Errors:%d",
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

    # ── Step 1: Connect to MySQL ──────────────────────────────
    mysql_conn = connect_mysql()
    if not mysql_conn:
        log.error("Could not connect to MySQL. Exiting.")
        sys.exit(1)

    # ── Step 2: Verify the alerts table exists ────────────────
    # All other tables are managed by create_tables.py.
    # We only verify alerts because that's the one the bridge writes to.
    try:
        cursor = mysql_conn.cursor()
        cursor.execute("SELECT 1 FROM alerts LIMIT 1;")
        cursor.fetchall()
        cursor.close()
        log.info("alerts table verified.")
    except MySQLError:
        log.error(
            "The 'alerts' table does not exist.\n"
            "  Run: python scripts/create_tables.py"
        )
        sys.exit(1)

    # ── Step 3: Resolve hardware_farm_id → integer farms.id ──
    # This must succeed before the bridge can insert anything.
    hardware_id = CONFIG["HARDWARE_FARM_ID"]
    farm_int_id = lookup_farm_id(mysql_conn, hardware_id)

    if farm_int_id is None:
        log.error(
            "Bridge cannot start — farm not found.\n"
            "  In your website admin panel:\n"
            "  Open the farm for this sensor node and set\n"
            "  hardware_farm_id = '%s'\n"
            "  Then restart the bridge.",
            hardware_id
        )
        sys.exit(1)

    log.info(
        "Farm ready: '%s' → farms.id = %d",
        hardware_id, farm_int_id
    )

    # ── Step 4: Connect to Firebase (non-fatal) ───────────────
    init_firebase()

    # ── Step 5: Open Bluetooth serial port ───────────────────
    bt_port = connect_bluetooth()
    if not bt_port:
        log.error("Could not open Bluetooth port. Exiting.")
        sys.exit(1)

    # ── Step 6: Main reading loop ─────────────────────────────
    log.info("Listening for sensor readings... (Ctrl+C to stop)")
    log.info("-" * 55)

    readings_since_stats = 0

    for reading in extract_json_from_serial(bt_port):

        # Check MySQL is still alive
        mysql_conn = ensure_mysql(mysql_conn)
        if not mysql_conn:
            log.error("MySQL unavailable. Skipping reading.")
            continue

        # If MySQL reconnected, re-resolve farm_int_id
        if farm_int_id is None:
            farm_int_id = lookup_farm_id(mysql_conn, hardware_id)
            if farm_int_id is None:
                log.error("Farm still not found. Skipping reading.")
                continue

        # Insert into MySQL
        inserted = insert_reading(mysql_conn, reading, farm_int_id)

        # Log any alert conditions (only on fresh inserts, not duplicates)
        if inserted:
            check_and_log_alerts(mysql_conn, reading, farm_int_id)

        # Sync to Firebase (always — fills gaps if WiFi was down on Arduino)
        sync_to_firebase(reading)

        # Print stats every 10 readings
        readings_since_stats += 1
        if readings_since_stats >= 10:
            print_stats()
            readings_since_stats = 0

    # ── Shutdown ──────────────────────────────────────────────
    log.info("-" * 55)
    log.info("Bridge stopped.")
    print_stats()

    if bt_port and bt_port.is_open:
        bt_port.close()
        log.info("Bluetooth port closed.")

    if mysql_conn and mysql_conn.is_connected():
        mysql_conn.close()
        log.info("MySQL connection closed.")


if __name__ == "__main__":
    main()