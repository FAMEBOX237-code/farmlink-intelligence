# ============================================================
# routes/public.py — FarmLink Intelligence
#
# Public-facing routes. No authentication required.
#
# ROUTES:
#   GET /              — Landing page
#   GET /about         — About us
#   GET /how-it-works  — How it works
#   GET /buyer/<id>    — Buyer profile (privacy gate for non-owners)
#   GET /farmer/<id>   — Farmer public profile
#   GET /search        — Global search (produce + farmers + buyers)
#   GET /search/quick  — JSON endpoint for live search dropdown
#   GET /403           — Direct 403 trigger (role guards)
#
# ERROR HANDLERS:
#   404 — Page not found
#   403 — Access denied
#   429 — Too many requests (rate limit)
#   500 — Internal server error
# ============================================================

from flask import Blueprint, render_template, abort, url_for, request, redirect, jsonify

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
# BUYER PROFILE PUBLIC VIEW  —  /buyer/<buyer_id>
# Visible to everyone — no login required.
# Shows buyer's public info: name, region, member since,
# completed purchases, ratings given, and active alerts count.
# Logged-in users who ARE that buyer are sent to their portal.
# ══════════════════════════════════════════════════════════════

@public_bp.route('/buyer/<int:buyer_id>')
def buyer_profile_public(buyer_id):
    from models.models import User as UserModel, Transaction, Rating, BuyerAlert
    from flask_login import current_user

    # 404 if buyer does not exist or is not a buyer
    subject = UserModel.query.filter_by(id=buyer_id, role='buyer').first()
    if not subject:
        from flask import abort
        abort(404)

    # Suspended buyers have no public profile
    if subject.is_suspended:
        from flask import abort
        abort(404)

    # If the requesting user IS this buyer — send to their own portal
    if current_user.is_authenticated and current_user.id == buyer_id:
        return redirect(url_for('buyer.profile'))

    # ── Public stats ──────────────────────────────────────────
    completed_purchases = Transaction.query.filter_by(
        buyer_id=buyer_id, status='completed').count()

    ratings_given = Rating.query.filter_by(
        buyer_id=buyer_id).count()

    active_alerts = BuyerAlert.query.filter_by(
        buyer_id=buyer_id, is_active=True).count()

    member_since = subject.created_at.strftime('%B %Y') \
        if subject.created_at else 'Unknown'

    return render_template(
        'buyer/profile_public.html',
        subject          = subject,
        completed_purchases = completed_purchases,
        ratings_given    = ratings_given,
        active_alerts    = active_alerts,
        member_since     = member_since,
        active_nav       = '',
    )


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

# ══════════════════════════════════════════════════════════════
# GLOBAL SEARCH  —  /search
# No login required. Searches across three entity types:
#   1. Produce listings  (active only)
#   2. Farmers           (verified + not suspended)
#   3. Buyers            (not suspended)
#
# URL param: q — the search string
# Returns grouped results rendered in search.html
# ══════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════
# QUICK SEARCH  —  /search/quick?q=...
# JSON endpoint for the live navbar dropdown.
# Returns up to 5 listings, 4 farmers, 3 buyers.
# Public — no login required.
# ══════════════════════════════════════════════════════════════

@public_bp.route('/search/quick')
def search_quick():
    from models.models import ProduceListing, User, Farm

    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify(listings=[], farmers=[], buyers=[])

    pattern = f'%{q}%'

    # ── Listings (up to 5) ────────────────────────────────────
    raw_listings = (ProduceListing.query
                    .filter(
                        ProduceListing.status == 'active',
                        db.or_(
                            ProduceListing.crop_type.ilike(pattern),
                            ProduceListing.description.ilike(pattern),
                        )
                    )
                    .order_by(ProduceListing.quality_score_live.desc())
                    .limit(5).all())

    listings_out = []
    for lst in raw_listings:
        farmer = User.query.get(lst.farmer_id)
        farm   = Farm.query.get(lst.farm_id)
        if not farmer or not farm:
            continue
        listings_out.append({
            'id':     lst.id,
            'crop':   lst.crop_type,
            'farm':   farm.name,
            'region': farm.region or '',
            'q':      lst.quality_score_live or 0,
            'photo':  lst.photo_url or '',
        })

    # ── Farmers (up to 4) ─────────────────────────────────────
    raw_farmers = (User.query
                   .filter(
                       User.role == 'farmer',
                       User.is_suspended == False,
                       db.or_(
                           User.full_name.ilike(pattern),
                           User.region.ilike(pattern),
                           User.primary_crop.ilike(pattern),
                       )
                   )
                   .order_by(User.trust_score.desc())
                   .limit(4).all())

    farmers_out = []
    for f in raw_farmers:
        ts = float(f.trust_score or 0)
        farmers_out.append({
            'id':       f.id,
            'name':     f.full_name,
            'region':   f.region or '—',
            'trust':    f'{ts:.1f}' if ts > 0 else '',
            'verified': f.is_verified,
            'photo':    f.profile_photo_url or '',
            'initials': (f.full_name[:2].upper() if f.full_name else '??'),
        })

    # ── Buyers (up to 3) ──────────────────────────────────────
    raw_buyers = (User.query
                  .filter(
                      User.role == 'buyer',
                      User.is_suspended == False,
                      db.or_(
                          User.full_name.ilike(pattern),
                          User.region.ilike(pattern),
                      )
                  )
                  .order_by(User.created_at.desc())
                  .limit(3).all())

    buyers_out = []
    for b in raw_buyers:
        buyers_out.append({
            'id':       b.id,
            'name':     b.full_name,
            'region':   b.region or '—',
            'photo':    b.profile_photo_url or '',
            'initials': (b.full_name[:2].upper() if b.full_name else '??'),
        })

    return jsonify(listings=listings_out, farmers=farmers_out, buyers=buyers_out)


@public_bp.route('/search')
def search():
    from models.models import ProduceListing, User, Farm
    from flask_login import current_user

    q = request.args.get('q', '').strip()

    listings_results = []
    farmer_results   = []
    buyer_results    = []

    if q:
        pattern = f'%{q}%'

        # ── Produce listings ──────────────────────────────────
        # Search active listings by crop type or description
        raw_listings = (ProduceListing.query
                        .filter(
                            ProduceListing.status == 'active',
                            db.or_(
                                ProduceListing.crop_type.ilike(pattern),
                                ProduceListing.description.ilike(pattern),
                            )
                        )
                        .order_by(ProduceListing.quality_score_live.desc())
                        .limit(20)
                        .all())

        for lst in raw_listings:
            farmer = User.query.get(lst.farmer_id)
            farm   = Farm.query.get(lst.farm_id)
            if not farmer or not farm:
                continue
            q_score = lst.quality_score_live or 0
            q_css   = 'high' if q_score >= 75 else ('medium' if q_score >= 50 else 'low')
            listings_results.append({
                'id':          lst.id,
                'crop':        lst.crop_type,
                'quantity':    float(lst.quantity_kg),
                'price':       float(lst.price_per_kg),
                'q_live':      q_score,
                'q_css':       q_css,
                'has_forecast': lst.forecast_id is not None,
                'photo_url':   lst.photo_url,
                'farm_name':   farm.name,
                'farm_region': farm.region or '',
                'farmer_name': farmer.full_name,
                'farmer_id':   farmer.id,
            })

        # ── Farmers ───────────────────────────────────────────
        # Search by name, region, or primary crop
        raw_farmers = (User.query
                       .filter(
                           User.role == 'farmer',
                           User.is_suspended == False,
                           db.or_(
                               User.full_name.ilike(pattern),
                               User.region.ilike(pattern),
                               User.primary_crop.ilike(pattern),
                           )
                       )
                       .order_by(User.trust_score.desc())
                       .limit(15)
                       .all())

        for farmer in raw_farmers:
            ts      = float(farmer.trust_score or 0)
            ts_css  = 'high' if ts >= 4.0 else ('medium' if ts >= 2.5 else 'low')
            farm_count = Farm.query.filter_by(owner_id=farmer.id).count()
            listing_count = ProduceListing.query.filter_by(
                farmer_id=farmer.id, status='active').count()
            farmer_results.append({
                'id':             farmer.id,
                'full_name':      farmer.full_name,
                'region':         farmer.region or '—',
                'primary_crop':   farmer.primary_crop or '—',
                'trust_score':    f'{ts:.1f}' if ts > 0 else '—',
                'ts_css':         ts_css,
                'is_verified':    farmer.is_verified,
                'farm_count':     farm_count,
                'listing_count':  listing_count,
                'photo_url':      farmer.profile_photo_url,
                'initials':       (farmer.full_name[:2].upper()
                                   if farmer.full_name else '??'),
            })

        # ── Buyers ────────────────────────────────────────────
        # Search by name or region only (protect privacy — no email)
        raw_buyers = (User.query
                      .filter(
                          User.role == 'buyer',
                          User.is_suspended == False,
                          db.or_(
                              User.full_name.ilike(pattern),
                              User.region.ilike(pattern),
                          )
                      )
                      .order_by(User.created_at.desc())
                      .limit(15)
                      .all())

        for buyer in raw_buyers:
            buyer_results.append({
                'id':        buyer.id,
                'full_name': buyer.full_name,
                'region':    buyer.region or '—',
                'photo_url': buyer.profile_photo_url,
                'initials':  (buyer.full_name[:2].upper()
                              if buyer.full_name else '??'),
            })

    total_results = len(listings_results) + len(farmer_results) + len(buyer_results)

    # Sidebar counts for logged-in users
    unread_notifs = 0
    active_alerts = 0
    if current_user.is_authenticated and current_user.is_buyer():
        from models.models import Notification, BuyerAlert
        unread_notifs = Notification.query.filter_by(
            recipient_id=current_user.id, is_read=False).count()
        active_alerts = BuyerAlert.query.filter_by(
            buyer_id=current_user.id, is_active=True).count()

    return render_template(
        'public/search.html',
        q                = q,
        total_results    = total_results,
        listings_results = listings_results,
        farmer_results   = farmer_results,
        buyer_results    = buyer_results,
        active_nav       = '',
        unread_notifs    = unread_notifs,
        active_alerts    = active_alerts,
    )


# ── Import db for OR queries above ───────────────────────────
from extensions import db


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