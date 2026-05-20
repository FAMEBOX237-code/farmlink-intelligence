# ============================================================
# app.py — FarmLink Intelligence
#
# Application factory. Creates and wires together every
# part of the Flask app — extensions, blueprints, and
# the database user loader.
#
# PATTERN: Application Factory
#   Instead of creating the app at module level, we define
#   create_app() and call it from the bottom of the file.
#   This pattern makes testing easier and prevents circular
#   imports because nothing runs until create_app() is called.
#
# BLUEPRINT REGISTRATION ORDER:
#   1. public_bp  — public pages + global error handlers
#   2. auth_bp    — /register /login /logout /reset-password
#   3. farmer_bp  — /farmer/* (requires farmer role)
#   4. buyer_bp   — /marketplace /listings/* /buyer/*
#   5. admin_bp   — /admin/* (requires admin role)
# ============================================================

from flask import Flask
from config import Config
from extensions import db, bcrypt, login_manager, mail, csrf, limiter
from flasgger import Swagger


# ── Swagger / Flasgger configuration ────────────────────────
SWAGGER_CONFIG = {
    'title'      : 'FarmLink Intelligence API',
    'uiversion'  : 3,
    'version'    : '1.0.0',
    'description': (
        'REST API for FarmLink Intelligence — IoT-verified smart agricultural '
        'marketplace for Cameroonian smallholder farmers.\n\n'
        'Built with Flask + SQLAlchemy. OOP design patterns: Observer, '
        'Strategy, Template Method.\n\n'
        '**Authentication**: Session-based (log in via /login first, '
        'then use authenticated endpoints).\n\n'
        '**Base URL**: http://127.0.0.1:5000'
    ),
    'termsOfService': '',
    'specs_route'   : '/api/docs/',
    'specs': [{
        'endpoint'   : 'apispec',
        'route'      : '/api/docs/apispec.json',
        'rule_filter': lambda rule: rule.endpoint.startswith('api'),
        'model_filter': lambda tag: True,
    }],
    'static_url_path': '/flasgger_static',
    'swagger_ui'     : True,
    'headers'        : [],
}


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # ── Initialise extensions (bind to app) ──────────────────
    db.init_app(app)
    bcrypt.init_app(app)
    login_manager.init_app(app)
    mail.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)
    Swagger(app, config=SWAGGER_CONFIG, merge=True)

    # ── Exempt API routes from CSRF ──────────────────────────
    # API endpoints receive JSON, not HTML forms.
    # CSRF protection is form-based and does not apply here.
    # API security is handled by session authentication instead.
    from routes.api import api_bp as _api_bp
    csrf.exempt(_api_bp)

    # ── User loader for Flask-Login ──────────────────────────
    # Flask-Login calls this on every request to load the
    # logged-in user from the session into current_user.
    from models.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # ── Register blueprints ──────────────────────────────────
    with app.app_context():
        from routes.public  import public_bp
        from routes.auth    import auth_bp
        from routes.farmer  import farmer_bp
        from routes.buyer   import buyer_bp
        from routes.admin   import admin_bp
        from routes.api     import api_bp

        app.register_blueprint(public_bp)
        app.register_blueprint(auth_bp)
        app.register_blueprint(farmer_bp)
        app.register_blueprint(buyer_bp)
        app.register_blueprint(admin_bp)
        app.register_blueprint(api_bp)

    # ── Prevent back-button from showing stale authenticated pages ──
    # Without these headers, clicking the browser back button after
    # logout returns to a cached version of the portal — the browser
    # shows the old page without making a new request to Flask.
    # These headers tell the browser: never cache authenticated pages.
    @app.after_request
    def add_no_cache_headers(response):
        """
        Add cache-control headers to every response.
        This prevents the back-button from showing stale pages
        after the user logs out.
        """
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma']        = 'no-cache'
        response.headers['Expires']       = '0'
        return response

    return app


# ── Entry point ──────────────────────────────────────────────
# Run with: python app.py
# Or with:  flask run
if __name__ == '__main__':
    application = create_app()
    application.run(debug=True)