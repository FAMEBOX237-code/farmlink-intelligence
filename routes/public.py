# ============================================================
# routes/public.py
#
# Public-facing routes — FarmLink Intelligence
# No authentication required for any route in this file.
#
# Routes:
#   GET  /              — Landing page
#   GET  /about         — About us
#   GET  /how-it-works  — How it works
#
# Error handlers:
#   404  — Page not found
#   403  — Access denied
#
# NOTE: /marketplace is handled by buyer_bp (routes/buyer.py)
# but is public (no login required). It is NOT in this file
# because it lives in the buyer portal namespace.
# ============================================================

from flask import Blueprint, render_template, abort

public_bp = Blueprint('public', __name__, url_prefix='')


# ── Landing page ──────────────────────────────────────────────
@public_bp.route('/')
def landing():
    return render_template('public/landing.html')


# ── About us ──────────────────────────────────────────────────
@public_bp.route('/about')
def about():
    return render_template('public/about.html')


# ── How it works ─────────────────────────────────────────────
@public_bp.route('/how-it-works')
def how_it_works():
    return render_template('public/how_it_works.html')


# ── Direct 403 trigger (used by role guard decorators) ───────
@public_bp.route('/403')
def forbidden_direct():
    """
    Role guard decorators in farmer.py, buyer.py, admin.py
    redirect here when a user tries to access a portal they
    don't belong to. This route explicitly aborts with 403
    so the app_errorhandler below catches it and renders
    the styled 403 page.
    """
    abort(403)


# ── Error handlers ────────────────────────────────────────────
@public_bp.app_errorhandler(404)
def not_found(e):
    return render_template('errors/404.html'), 404


@public_bp.app_errorhandler(403)
def forbidden(e):
    return render_template('errors/403.html'), 403