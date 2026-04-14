# ============================================================
# config.py — FarmLink Intelligence
#
# All application configuration lives here.
# Values are loaded from the .env file — secrets NEVER
# appear in this file directly.
#
# HOW IT WORKS:
#   1. .env stores the actual values (SECRET_KEY, passwords…)
#   2. config.py reads them with os.getenv()
#   3. app.py loads this class with app.config.from_object(Config)
#   4. Every part of the app reads from app.config
#
# NEVER commit your .env file to Git.
# The .env.example file is safe to commit (no real values).
# ============================================================

import os
from dotenv import load_dotenv

load_dotenv()


class Config:

    # ── Core security ─────────────────────────────────────────
    # Must be a long random string in production.
    # Generate one with: python -c "import secrets; print(secrets.token_hex(32))"
    SECRET_KEY = os.getenv('SECRET_KEY', 'change-this-in-production')

    # ── Database ──────────────────────────────────────────────
    SQLALCHEMY_DATABASE_URI = os.getenv(
        'DATABASE_URL',
        'mysql+pymysql://root:farmlink123@localhost/farmlink'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_recycle': 280,        # recycle connections before MySQL's 8-hour timeout
        'pool_pre_ping': True,      # test connection before using it
    }

    # ── Session security ─────────────────────────────────────
    SESSION_COOKIE_HTTPONLY  = True   # JS cannot read the session cookie
    SESSION_COOKIE_SAMESITE  = 'Lax'  # protects against CSRF from other sites
    SESSION_COOKIE_SECURE    = os.getenv('FLASK_ENV') == 'production'  # HTTPS only in prod
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 7   # sessions last 7 days

    # ── CSRF protection (Flask-WTF) ───────────────────────────
    WTF_CSRF_ENABLED      = True
    WTF_CSRF_TIME_LIMIT   = 3600    # CSRF token valid for 1 hour
    WTF_CSRF_SSL_STRICT   = False   # set True when you have HTTPS

    # ── Email (Flask-Mail) ───────────────────────────────────
    # Used for password reset emails.
    # In development, set MAIL_SUPPRESS_SEND=True to avoid
    # sending real emails — they will be printed to the console.
    MAIL_SERVER        = os.getenv('MAIL_SERVER',   'smtp.gmail.com')
    MAIL_PORT          = int(os.getenv('MAIL_PORT', '587'))
    MAIL_USE_TLS       = os.getenv('MAIL_USE_TLS',  'true').lower() == 'true'
    MAIL_USE_SSL       = os.getenv('MAIL_USE_SSL',  'false').lower() == 'true'
    MAIL_USERNAME      = os.getenv('MAIL_USERNAME', '')
    MAIL_PASSWORD      = os.getenv('MAIL_PASSWORD', '')
    MAIL_DEFAULT_SENDER= os.getenv('MAIL_DEFAULT_SENDER', 'noreply@farmlink.cm')
    MAIL_SUPPRESS_SEND = os.getenv('MAIL_SUPPRESS_SEND', 'true').lower() == 'true'

    # ── Password reset token ──────────────────────────────────
    # Token expires after this many seconds (30 minutes)
    PASSWORD_RESET_EXPIRY = 1800

    # ── File uploads ─────────────────────────────────────────
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024   # 5 MB max upload
    UPLOAD_FOLDER      = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
    ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}

    # ── Rate limiting (Flask-Limiter) ─────────────────────────
    RATELIMIT_STORAGE_URI    = 'memory://'
    RATELIMIT_DEFAULT        = []            # no global limit — set per-route
    RATELIMIT_HEADERS_ENABLED= True