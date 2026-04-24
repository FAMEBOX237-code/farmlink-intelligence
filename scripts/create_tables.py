# ============================================================
# create_tables.py — FarmLink Intelligence
#
# ONE-TIME setup script. Run this ONCE after cloning the
# project to create all database tables.
#
# HOW TO RUN:
#   python create_tables.py
#
# WHAT IT DOES:
#   1. Reads DATABASE_URL from your .env file
#   2. Connects to MySQL
#   3. Creates the 'farmlink' database if it does not exist
#   4. Creates every table defined in models/models.py
#   5. Prints a confirmation for each table
#
# SAFE TO RE-RUN:
#   Uses CREATE TABLE IF NOT EXISTS — will not overwrite
#   existing tables or delete any data.
#
# AFTER RUNNING THIS:
#   Run seed.py to create the admin account.
# ============================================================

import os
import sys

# Make sure we can import from the project root
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from app import create_app
from extensions import db

# Import all models so SQLAlchemy knows about them
from models.models import (
    User, Farm, SensorReading, HarvestForecast,
    ProduceListing, Transaction, Rating,
    BuyerAlert, Notification, ContactRequest
)


def create_database_if_missing():
    """
    Attempts to create the MySQL database itself if it doesn't
    exist yet. This handles the case where MySQL is fresh and
    the 'farmlink' database has never been created.
    """
    import pymysql
    from urllib.parse import urlparse

    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        print("  ERROR: DATABASE_URL is not set in your .env file.")
        print("  Cannot create database. Add DATABASE_URL to .env and try again.")
        sys.exit(1)

    # Parse the URL to extract components
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
        print(f"✓ Database '{db_name}' is ready.")
    except Exception as e:
        print(f"  Could not auto-create database: {e}")
        print(f"  Create it manually: CREATE DATABASE {db_name};")


def create_all_tables():
    app = create_app()
    with app.app_context():
        print("\nCreating all tables...\n")
        db.create_all()

        # List what was created
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()

        for table in sorted(tables):
            print(f"  ✓ {table}")

        print(f"\n{len(tables)} table(s) ready in the database.")
        print("\nNext step: run   python seed.py   to create the admin account.")


if __name__ == '__main__':
    print("FarmLink Intelligence — Database Setup")
    print("=" * 40)
    create_database_if_missing()
    create_all_tables()