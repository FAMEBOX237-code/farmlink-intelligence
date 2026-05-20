# ============================================================
# seed.py — FarmLink Intelligence
#
# Creates the initial admin account and optional test data.
#
# HOW TO RUN:
#   python seed.py
#
# Run this AFTER create_tables.py.
#
# WHAT IT CREATES:
#   1. One admin account (email + password from .env or defaults)
#   2. Optional: one test farmer + one test buyer for development
#
# SAFE TO RE-RUN:
#   Checks if each account already exists before creating.
#   Will never create duplicates.
# ============================================================

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

from app import create_app
from extensions import db, bcrypt
from models.models import User


# ── Admin credentials ─────────────────────────────────────────
# Change these in .env before running in production.
# Do NOT hardcode real passwords here.
ADMIN_EMAIL    = os.getenv('ADMIN_EMAIL')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD')
ADMIN_NAME     = os.getenv('ADMIN_NAME',     'FarmLink Administrator')

# ── Test accounts (development only) ─────────────────────────
TEST_FARMER_EMAIL    = 'farmer@farmlink.cm'
TEST_FARMER_PASSWORD = os.getenv('TEST_FARMER_PASSWORD', 'Farmer2026!')

TEST_BUYER_EMAIL     = 'buyer@farmlink.cm'
TEST_BUYER_PASSWORD  = os.getenv('TEST_BUYER_PASSWORD', 'Buyer2026!')


def create_user_if_missing(full_name, email, password, role, **kwargs):
    """Create a user only if that email is not already in the database."""
    existing = User.query.filter_by(email=email).first()
    if existing:
        print(f'  → already exists: {email}')
        return existing

    password_hash = bcrypt.generate_password_hash(password).decode('utf-8')
    user = User(
        full_name     = full_name,
        email         = email,
        password_hash = password_hash,
        role          = role,
        is_verified   = True,
        is_suspended  = False,
        **kwargs
    )
    db.session.add(user)
    db.session.commit()
    print(f'  ✓ created: {email}  [{role}]  password: {password}')
    return user


def run_seed():
    app = create_app()
    with app.app_context():
        print('\nFarmLink Intelligence — Database Seed')
        print('=' * 40)

        # Safety check — refuse to run without real admin credentials
        if not ADMIN_EMAIL or not ADMIN_PASSWORD:
            print('\n  ERROR: ADMIN_EMAIL and ADMIN_PASSWORD must be set in your .env file.')
            print('  Add them and try again. Never hardcode credentials.')
            return

        print('\n[1] Admin account')
        create_user_if_missing(
            full_name = ADMIN_NAME,
            email     = ADMIN_EMAIL,
            password  = ADMIN_PASSWORD,
            role      = 'admin',
        )

        print('\n[2] Test farmer account (development only)')
        create_user_if_missing(
            full_name    = 'Test Farmer — Paul Nkeng',
            email        = TEST_FARMER_EMAIL,
            password     = TEST_FARMER_PASSWORD,
            role         = 'farmer',
            region       = 'West',
            primary_crop = 'Tomatoes',
            trust_score  = 4.2,
        )

        print('\n[3] Test buyer account (development only)')
        create_user_if_missing(
            full_name = 'Test Buyer — Marie Ekane',
            email     = TEST_BUYER_EMAIL,
            password  = TEST_BUYER_PASSWORD,
            role      = 'buyer',
            region    = 'Littoral',
        )

        print('\n' + '=' * 40)
        print('Seed complete. You can now log in with:')
        print(f'  Admin   → {ADMIN_EMAIL}  /  {ADMIN_PASSWORD}')
        print(f'  Farmer  → {TEST_FARMER_EMAIL}  /  {TEST_FARMER_PASSWORD}')
        print(f'  Buyer   → {TEST_BUYER_EMAIL}  /  {TEST_BUYER_PASSWORD}')
        print()


if __name__ == '__main__':
    run_seed()