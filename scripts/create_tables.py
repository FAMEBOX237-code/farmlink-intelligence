# ============================================================
# scripts/create_tables.py — FarmLink Intelligence
#
# ONE-TIME setup script. Run this ONCE after cloning the
# project to create all database tables.
#
# HOW TO RUN:
#   python scripts/create_tables.py
#   (from the project root)
#
# WHAT IT DOES:
#   1. Reads DATABASE_URL from your .env file
#   2. Creates the 'farmlink' database if it does not exist
#   3. Skips legacy table drop — existing data is preserved
#   4. Creates every table defined in models/models.py
#   5. Installs the calculate_quality_score MySQL trigger
#   6. Verifies all 12 tables and the trigger are present
#
# SAFE TO RE-RUN:
#   Uses CREATE TABLE IF NOT EXISTS — will not overwrite
#   existing tables or delete any data.
#   The trigger is dropped and recreated each run to stay
#   in sync with any formula changes.
#
# AFTER RUNNING THIS:
#   Run seed.py to create the admin account.
#
# TABLE LIST (12 tables):
#   users, farms, sensor_readings, irrigation_log,
#   harvest_forecasts, produce_listings, transactions,
#   ratings, buyer_alerts, notifications, contact_requests,
#   alerts
#
# HARDWARE SCHEMA NOTES:
#   sensor_readings  — PK is id INTEGER (auto-increment, website standard)
#                      reading_id VARCHAR(36) UNIQUE (bridge idempotency key)
#                      farm_id INTEGER → farms.id
#                      light_intensity nullable
#   irrigation_log   — farm_id INTEGER → farms.id
#   alerts           — reading_id plain VARCHAR (no FK), farm_id plain INTEGER (no FK)
# ============================================================

import os
import sys

# Make sure we can import from the project root
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

from app import create_app
from extensions import db

# Import all models so SQLAlchemy knows about every table
from models.models import (
    User, Farm, SensorReading, Alert, IrrigationLog, HarvestForecast,
    ProduceListing, Transaction, Rating,
    BuyerAlert, Notification, ContactRequest
)


# ── The quality-score trigger ────────────────────────────────
# Fires AFTER every INSERT into sensor_readings.
# Calculates a weighted quality score (0–100) and writes it
# back to sensor_readings.quality_score using reading_id (the
# VARCHAR PK), then updates farms.current_quality_score with
# a rolling average of the last 10 readings for that farm
# (joined via farms.hardware_farm_id).
#
# Formula weights:
#   Soil moisture  40 %
#   Temperature    30 %
#   Humidity       20 %
#   Heat-stress    10 %  (penalty flag from Arduino)
QUALITY_SCORE_TRIGGER = """
CREATE TRIGGER calculate_quality_score
AFTER INSERT ON sensor_readings
FOR EACH ROW
BEGIN
    DECLARE v_soil_score     DECIMAL(5,2);
    DECLARE v_temp_score     DECIMAL(5,2);
    DECLARE v_humidity_score DECIMAL(5,2);
    DECLARE v_heat_penalty   DECIMAL(5,2);
    DECLARE v_final_score    DECIMAL(5,2);

    IF NEW.soil_moisture IS NOT NULL
       AND NEW.temperature IS NOT NULL
       AND NEW.humidity    IS NOT NULL
    THEN

        -- FACTOR 1: SOIL MOISTURE (weight 40%)
        SET v_soil_score =
            CASE
                WHEN NEW.soil_moisture BETWEEN 40.0 AND 70.0 THEN 100.0
                WHEN NEW.soil_moisture BETWEEN 70.0 AND 85.0 THEN  80.0
                WHEN NEW.soil_moisture BETWEEN 30.0 AND 40.0 THEN  70.0
                WHEN NEW.soil_moisture > 85.0                THEN  50.0
                WHEN NEW.soil_moisture < 30.0                THEN  40.0
                ELSE 50.0
            END;

        -- FACTOR 2: TEMPERATURE (weight 30%)
        SET v_temp_score =
            CASE
                WHEN NEW.temperature BETWEEN 20.0 AND 30.0 THEN 100.0
                WHEN NEW.temperature BETWEEN 15.0 AND 20.0 THEN  80.0
                WHEN NEW.temperature BETWEEN 30.0 AND 35.0 THEN  75.0
                WHEN NEW.temperature > 35.0                THEN  40.0
                WHEN NEW.temperature < 15.0                THEN  50.0
                ELSE 60.0
            END;

        -- FACTOR 3: HUMIDITY (weight 20%)
        SET v_humidity_score =
            CASE
                WHEN NEW.humidity BETWEEN 50.0 AND 80.0 THEN 100.0
                WHEN NEW.humidity BETWEEN 40.0 AND 50.0 THEN  75.0
                WHEN NEW.humidity BETWEEN 80.0 AND 90.0 THEN  70.0
                WHEN NEW.humidity < 40.0                 THEN  50.0
                WHEN NEW.humidity > 90.0                 THEN  55.0
                ELSE 60.0
            END;

        -- FACTOR 4: HEAT STRESS PENALTY (weight 10%)
        SET v_heat_penalty =
            CASE
                WHEN NEW.heat_stress_flag = 1 THEN  30.0
                ELSE                               100.0
            END;

        -- WEIGHTED FINAL SCORE
        SET v_final_score = ROUND(
            (v_soil_score     * 0.40) +
            (v_temp_score     * 0.30) +
            (v_humidity_score * 0.20) +
            (v_heat_penalty   * 0.10),
            2
        );

        -- Write score back using integer id (the PK)
        UPDATE sensor_readings
            SET quality_score = v_final_score
        WHERE id = NEW.id;

        -- Update farms.current_quality_score (rolling avg last 10 readings)
        -- farm_id in sensor_readings maps to farms.id (integer)
        UPDATE farms
            SET current_quality_score = (
                SELECT ROUND(AVG(quality_score), 0)
                FROM (
                    SELECT quality_score
                    FROM sensor_readings
                    WHERE farm_id = NEW.farm_id
                      AND quality_score IS NOT NULL
                    ORDER BY recorded_at DESC
                    LIMIT 10
                ) AS recent
            )
        WHERE id = NEW.farm_id;

    END IF;

END
"""


def create_database_if_missing():
    """
    Connects directly to MySQL (no database selected) and
    creates the farmlink database if it does not exist yet.
    Handles a completely fresh MySQL installation.
    """
    import pymysql
    from urllib.parse import urlparse

    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        print("  ERROR: DATABASE_URL is not set in your .env file.")
        print("  Add it and try again. Example:")
        print("  DATABASE_URL=mysql+pymysql://root:password@localhost/farmlink")
        sys.exit(1)

    parsed   = urlparse(db_url.replace('mysql+pymysql://', 'mysql://'))
    host     = parsed.hostname or 'localhost'
    port     = parsed.port or 3306
    user     = parsed.username or 'root'
    password = parsed.password or ''
    db_name  = parsed.path.lstrip('/')

    try:
        conn = pymysql.connect(host=host, port=port, user=user, password=password)
        cursor = conn.cursor()
        cursor.execute(
            f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
            f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
        )
        conn.commit()
        conn.close()
        print(f"  ✓ Database '{db_name}' is ready.")
    except Exception as e:
        print(f"  Could not auto-create database: {e}")
        print(f"  Create it manually:  CREATE DATABASE {db_name};")
        sys.exit(1)


def create_all_tables(app):
    """
    Calls db.create_all() which creates every table that does
    not already exist, using the ORM model definitions as the
    source of truth for column names, types, and constraints.

    Tables created (12 total):
      users, farms, sensor_readings, alerts, irrigation_log,
      harvest_forecasts, produce_listings, transactions,
      ratings, buyer_alerts, notifications, contact_requests
    """
    with app.app_context():
        db.create_all()

        from sqlalchemy import inspect
        tables = sorted(inspect(db.engine).get_table_names())

        for table in tables:
            print(f'  ✓ {table}')

        print(f'\n  {len(tables)} table(s) present in the database.')


def install_trigger(app):
    """
    Installs the calculate_quality_score trigger.

    db.create_all() only creates tables — it never creates
    triggers, views, or stored procedures. This function fills
    that gap by running the trigger DDL directly via the engine.

    The trigger is dropped first so this function is safe to
    re-run (e.g. after updating the formula weights).

    Key implementation details:
      - Uses reading_id (VARCHAR PK) not id (no integer PK exists)
      - Updates farms via hardware_farm_id not farms.id
    """
    with app.app_context():
        from sqlalchemy import text

        # Drop the old trigger if it exists
        db.session.execute(text('DROP TRIGGER IF EXISTS calculate_quality_score;'))
        db.session.commit()

        # Create the trigger (no DELIMITER needed — SQLAlchemy
        # executes one statement at a time)
        db.session.execute(text(QUALITY_SCORE_TRIGGER))
        db.session.commit()

        print('  ✓ calculate_quality_score trigger installed.')


def verify(app):
    """
    Post-install sanity check.
    Verifies that all 12 expected tables exist, that key columns
    are present in sensor_readings, farms, and alerts, and that
    the calculate_quality_score trigger is installed.
    """
    with app.app_context():
        from sqlalchemy import inspect, text

        inspector = inspect(db.engine)
        existing  = set(inspector.get_table_names())

        # ── 12 tables total — alerts added in Phase 5.6 ───────
        expected_tables = [
            'users', 'farms', 'sensor_readings', 'irrigation_log',
            'harvest_forecasts', 'produce_listings', 'transactions',
            'ratings', 'buyer_alerts', 'notifications', 'contact_requests',
            'alerts',
        ]

        all_ok = True
        for t in expected_tables:
            if t not in existing:
                print(f'  ✗ MISSING table: {t}')
                all_ok = False

        # ── Verify farms has all expected columns ─────────────
        farms_cols = {c['name'] for c in inspector.get_columns('farms')}
        required_farms = {
            'id', 'owner_id', 'name', 'region', 'town', 'crop_type',
            'size_hectares', 'latitude', 'longitude', 'sensor_node_id',
            'hardware_farm_id', 'farmer_name', 'farmer_phone',
            'current_quality_score', 'is_active', 'notes',
            'created_at', 'updated_at',
        }
        missing_farms = required_farms - farms_cols
        if missing_farms:
            print(f'  ✗ farms table is missing columns: {sorted(missing_farms)}')
            all_ok = False
        else:
            print('  ✓ farms columns verified.')

        # ── Verify sensor_readings has correct columns ─────────
        if 'sensor_readings' in existing:
            sr_cols = {c['name'] for c in inspector.get_columns('sensor_readings')}
            required_sr = {
                'id', 'reading_id', 'farm_id', 'recorded_at', 'inserted_at',
                'temperature', 'humidity', 'soil_moisture', 'light_intensity',
                'is_raining', 'rain_intensity',
                'heat_stress_flag', 'irrigation_active',
                'quality_score', 'sync_status',
            }
            missing_sr = required_sr - sr_cols
            if missing_sr:
                print(f'  ✗ sensor_readings missing columns: {sorted(missing_sr)}')
                all_ok = False
            else:
                print('  ✓ sensor_readings columns verified.')

        # ── Verify irrigation_log columns ─────────────────────
        if 'irrigation_log' in existing:
            il_cols = {c['name'] for c in inspector.get_columns('irrigation_log')}
            required_il = {
                'event_id', 'farm_id', 'started_at',
                'duration_seconds', 'trigger_moisture',
                'trigger_type', 'notes',
            }
            missing_il = required_il - il_cols
            if missing_il:
                print(f'  ✗ irrigation_log missing columns: {sorted(missing_il)}')
                all_ok = False
            else:
                print('  ✓ irrigation_log columns verified.')

        # ── Verify alerts table has expected columns ───────────
        if 'alerts' in existing:
            al_cols = {c['name'] for c in inspector.get_columns('alerts')}
            required_al = {
                'alert_id', 'reading_id', 'farm_id',
                'alert_type', 'alert_value', 'triggered_at',
            }
            missing_al = required_al - al_cols
            if missing_al:
                print(f'  ✗ alerts missing columns: {sorted(missing_al)}')
                all_ok = False
            else:
                print('  ✓ alerts columns verified.')

        # ── Verify trigger exists ─────────────────────────────
        result = db.session.execute(
            text("SELECT TRIGGER_NAME FROM information_schema.TRIGGERS "
                 "WHERE TRIGGER_SCHEMA = DATABASE() "
                 "AND TRIGGER_NAME = 'calculate_quality_score';")
        ).fetchone()
        if result:
            print('  ✓ calculate_quality_score trigger present.')
        else:
            print('  ✗ calculate_quality_score trigger NOT found.')
            all_ok = False

        return all_ok


if __name__ == '__main__':
    print('\nFarmLink Intelligence — Database Setup')
    print('=' * 42)

    print('\n[1/5] Checking database...')
    create_database_if_missing()

    app = create_app()

    print('\n[2/5] Skipping legacy table drop — preserving existing data.')

    print('\n[3/5] Creating all tables from models...')
    create_all_tables(app)

    print('\n[4/5] Installing MySQL trigger...')
    install_trigger(app)

    print('\n[5/5] Verifying installation...')
    ok = verify(app)

    print('\n' + '=' * 42)
    if ok:
        print('  All 12 tables present. Trigger installed.')
        print('  Next step: run   python scripts/seed.py   to create the admin account.')
    else:
        print('  Setup completed with warnings. Review the errors above.')
    print()