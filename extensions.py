# ============================================================
# extensions.py — FarmLink Intelligence
#
# This file creates all Flask extension instances WITHOUT
# binding them to an app. They are initialised later inside
# create_app() using the init_app() pattern.
#
# WHY THIS FILE EXISTS:
#   Flask extensions like SQLAlchemy and Flask-Login need to
#   be imported by both app.py (to initialise) and models.py
#   (to define tables). If models.py imported directly from
#   app.py it would create a circular import and crash.
#   This file breaks that cycle — everyone imports from here.
#
# USAGE:
#   from extensions import db, bcrypt, login_manager, mail, csrf
# ============================================================

from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_bcrypt import Bcrypt
from flask_mail import Mail
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# ── Database ORM ─────────────────────────────────────────────
db = SQLAlchemy()

# ── Password hashing ─────────────────────────────────────────
bcrypt = Bcrypt()

# ── Session-based authentication ─────────────────────────────
login_manager = LoginManager()
login_manager.login_view         = 'auth.login'
login_manager.login_message      = 'Please log in to access this page.'
login_manager.login_message_category = 'info'

# ── Email sending (password reset) ───────────────────────────
mail = Mail()

# ── CSRF protection on all POST forms ────────────────────────
csrf = CSRFProtect()

# ── Rate limiting (brute-force protection) ───────────────────
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],          # no global limit — set per-route
    storage_uri='memory://',    # use Redis in production
)