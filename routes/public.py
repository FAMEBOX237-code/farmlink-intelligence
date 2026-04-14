# ============================================================
# routes/public.py — FarmLink Intelligence
#
# Public-facing routes. No authentication required.
#
# ROUTES:
#   GET /              — Landing page
#   GET /about         — About us
#   GET /how-it-works  — How it works
#   GET /403           — Direct 403 trigger (role guards)
#
# ERROR HANDLERS:
#   404 — Page not found
#   403 — Access denied
#   429 — Too many requests (rate limit)
#   500 — Internal server error
# ============================================================

from flask import Blueprint, render_template, abort

public_bp = Blueprint('public', __name__, url_prefix='')


# ── Public pages ──────────────────────────────────────────────
@public_bp.route('/')
def landing():
    return render_template('public/landing.html')


@public_bp.route('/about')
def about():
    return render_template('public/about.html')


@public_bp.route('/how-it-works')
def how_it_works():
    return render_template('public/how_it_works.html')


@public_bp.route('/403')
def forbidden_direct():
    """
    Role guard decorators in farmer.py, buyer.py, admin.py
    redirect here when the wrong role tries to access a portal.
    We abort with 403 so the error handler below renders the
    styled 403 page.
    """
    abort(403)


# ── Error handlers ────────────────────────────────────────────
# These are global — they catch errors from every blueprint,
# not just the public one.

@public_bp.app_errorhandler(404)
def not_found(e):
    """Page does not exist."""
    return render_template('errors/404.html'), 404


@public_bp.app_errorhandler(403)
def forbidden(e):
    """Access denied — wrong role or not logged in."""
    return render_template('errors/403.html'), 403


@public_bp.app_errorhandler(429)
def too_many_requests(e):
    """
    Rate limit exceeded.
    Flask-Limiter raises this when a POST form is submitted
    too many times. The 429.html page shows which limits apply
    and counts down until the user can try again.

    Triggered by the @limiter.limit() decorators in auth.py.
    Never triggered by page views — only form submissions.
    """
    return render_template('errors/429.html'), 429


@public_bp.app_errorhandler(500)
def internal_error(e):
    """
    Unexpected server error.
    Shows a clean error page instead of the Flask debug traceback
    in production. In development (debug=True), Flask still shows
    the interactive debugger — this handler only fires in production.
    """
    return render_template('errors/500.html'), 500