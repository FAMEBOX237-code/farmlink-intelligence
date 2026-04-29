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

from flask import Blueprint, render_template, abort, url_for, request, redirect

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



# ══════════════════════════════════════════════════════════════
# FARMER PROFILE — PUBLIC VIEW (WF18)
# No login required. Shows only: name, region, verified badge,
# trust score number (no breakdown), farm regions only.
# CTA to register/login to see more.
# ══════════════════════════════════════════════════════════════

@public_bp.route('/farmer/<int:farmer_id>')
def farmer_profile_public(farmer_id):
    from models.models import User as UserModel, Farm, ProduceListing
    from flask_login import current_user

    subject = UserModel.query.filter_by(id=farmer_id, role='farmer').first()
    if not subject:
        from flask import abort
        abort(404)

    # Redirect logged-in users to the richer registered view
    if current_user.is_authenticated:
        return redirect(url_for('farmer.farmer_profile_registered', farmer_id=farmer_id))

    farm_list   = Farm.query.filter_by(owner_id=farmer_id).all()
    farm_regions = list(dict.fromkeys(f.region for f in farm_list if f.region))
    farm_count  = len(farm_list)

    ts_val = float(subject.trust_score) if subject.trust_score else 0.0
    ts_display = f'{ts_val:.1f}' if ts_val > 0 else None

    listing_count = ProduceListing.query.filter_by(
        farmer_id=farmer_id, status='active').count()

    return render_template('farmer/profile_public.html',
        subject_farmer=subject,
        farm_count=farm_count,
        farm_regions=farm_regions,
        trust_score_display=ts_display,
        active_listing_count=listing_count,
    )

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