# ============================================================
# routes/farmer.py
#
# Farmer portal routes — FarmLink Intelligence
#
# All routes in this file require:
#   1. The user to be logged in (@login_required)
#   2. The user to have role == 'farmer' (checked by
#      the farmer_required decorator defined below)
#
# Routes defined here:
#   GET  /farmer/dashboard        — Farmer home screen
#   GET  /farmer/farms            — My farms list
#   GET  /farmer/farms/new        — Add / edit farm
#   GET  /farmer/listings         — My listings list
#   GET  /farmer/listings/new     — New listing form
#   GET  /farmer/listings/<id>    — Edit listing
#   GET  /farmer/forecasts/<id>   — Forecast detail
#   GET  /farmer/trust            — Trust score page
#   GET  /farmer/notifications    — Notifications
#   GET  /farmer/profile          — Profile & settings
#
# BUILD ORDER (follow Sprint plan in design spec):
#   Stage 4 → Stage 5 → Stage 6 → Stage 7
# ============================================================

from functools import wraps
from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user

farmer_bp = Blueprint('farmer', __name__, url_prefix='/farmer')


# ── Role guard decorator ──────────────────────────────────────
def farmer_required(f):
    """
    Decorator: ensures the logged-in user is a farmer.
    If not, redirects to 403 (Access Denied).
    Use AFTER @login_required.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'farmer':
            return redirect(url_for('public.forbidden_direct'))
        return f(*args, **kwargs)
    return decorated


# ══════════════════════════════════════════════════════════════
# FARMER DASHBOARD  —  /farmer/dashboard
# ══════════════════════════════════════════════════════════════
@farmer_bp.route('/dashboard')
@login_required
@farmer_required
def dashboard():
    """
    Farmer home screen.

    TODO Sprint 4: Query and pass to template:
      - farmer = current_user
      - farms  = Farm.query.filter_by(owner_id=current_user.id).all()
      - latest_readings per farm from SensorReading
      - active_listings count from ProduceListing
      - trust_score from current_user.trust_score
      - active_forecasts from HarvestForecast
      - recent_alerts from Notification (last 5)
    """
    return render_template('farmer/dashboard.html')


# ══════════════════════════════════════════════════════════════
# MY FARMS  —  /farmer/farms
# ══════════════════════════════════════════════════════════════
@farmer_bp.route('/farms')
@login_required
@farmer_required
def farms():
    """
    Lists all farms belonging to the logged-in farmer.

    TODO Sprint 4:
      - farms = Farm.query.filter_by(owner_id=current_user.id).all()
      - For each farm, attach latest SensorReading
      - Compute online/offline status (last reading > 30 min ago = offline)
    """
    return render_template('farmer/farms.html')


# ══════════════════════════════════════════════════════════════
# ADD FARM  —  /farmer/farms/new
# ══════════════════════════════════════════════════════════════
@farmer_bp.route('/farms/new', methods=['GET', 'POST'])
@login_required
@farmer_required
def add_farm():
    """
    Three-step wizard: Farm details → Sensor setup → Confirm.

    TODO Sprint 4:
      GET:  Render the empty form.
      POST: Validate, create Farm row, link sensor_node_id.
            Redirect to /farmer/farms on success.
    """
    return render_template('farmer/add_farm.html')


# ══════════════════════════════════════════════════════════════
# EDIT FARM  —  /farmer/farms/<int:farm_id>
# ══════════════════════════════════════════════════════════════
@farmer_bp.route('/farms/<int:farm_id>', methods=['GET', 'POST'])
@login_required
@farmer_required
def edit_farm(farm_id):
    """
    Pre-fills the add_farm form with existing farm data.
    Also includes the Delist zone at the bottom.

    TODO Sprint 4:
      farm = Farm.query.get_or_404(farm_id)
      Verify farm.owner_id == current_user.id (else 403).
    """
    return render_template('farmer/edit_farm.html', farm_id=farm_id)


# ══════════════════════════════════════════════════════════════
# MY LISTINGS  —  /farmer/listings
# ══════════════════════════════════════════════════════════════
@farmer_bp.route('/listings')
@login_required
@farmer_required
def listings():
    """
    Tabbed view: All / Active / Sold / Drafts.

    TODO Sprint 6:
      listings = ProduceListing.query.filter_by(farmer_id=current_user.id).all()
      Group by status for tab counts.
    """
    return render_template('farmer/listings.html')


# ══════════════════════════════════════════════════════════════
# NEW LISTING  —  /farmer/listings/new
# ══════════════════════════════════════════════════════════════
@farmer_bp.route('/listings/new', methods=['GET', 'POST'])
@login_required
@farmer_required
def new_listing():
    """
    Four-step wizard to create a produce listing.
    Step 4 auto-attaches quality score and trust score.

    TODO Sprint 6:
      POST: Validate all fields, create ProduceListing.
      Quality score is pulled from farm.current_quality_score.
      Status = 'draft' or 'active' depending on button clicked.
    """
    return render_template('farmer/listing_new.html')


# ══════════════════════════════════════════════════════════════
# EDIT LISTING  —  /farmer/listings/<int:listing_id>
# ══════════════════════════════════════════════════════════════
@farmer_bp.route('/listings/<int:listing_id>', methods=['GET', 'POST'])
@login_required
@farmer_required
def edit_listing(listing_id):
    """
    Pre-fills the listing form. Shows live preview panel.
    Includes the Delist zone at the bottom of the page.

    TODO Sprint 6:
      listing = ProduceListing.query.get_or_404(listing_id)
      Verify listing.farmer_id == current_user.id (else 403).
    """
    return render_template('farmer/listing_edit.html', listing_id=listing_id)


# ══════════════════════════════════════════════════════════════
# FORECAST DETAIL  —  /farmer/forecasts/<int:forecast_id>
# ══════════════════════════════════════════════════════════════
@farmer_bp.route('/forecasts/<int:forecast_id>')
@login_required
@farmer_required
def forecast_detail(forecast_id):
    """
    Full forecast detail: 28-day trend chart, confidence
    breakdown, buyers alerted list, event timeline.

    TODO Sprint 7:
      forecast = HarvestForecast.query.get_or_404(forecast_id)
      Verify forecast.farm.owner_id == current_user.id.
    """
    return render_template('farmer/forecast_detail.html', forecast_id=forecast_id)


# ══════════════════════════════════════════════════════════════
# TRUST SCORE  —  /farmer/trust
# ══════════════════════════════════════════════════════════════
@farmer_bp.route('/trust')
@login_required
@farmer_required
def trust_score():
    """
    Trust score breakdown: completion rate, on-time delivery,
    buyer ratings, profile completeness. Four progress bars.

    TODO Sprint 7: Pull from TrustScoreEngine.
    """
    return render_template('farmer/trust_score.html')


# ══════════════════════════════════════════════════════════════
# NOTIFICATIONS  —  /farmer/notifications
# ══════════════════════════════════════════════════════════════
@farmer_bp.route('/notifications')
@login_required
@farmer_required
def notifications():
    """
    Notification inbox — system alerts, buyer enquiries.

    TODO Sprint 7:
      notifications = Notification.query.filter_by(
          recipient_id=current_user.id
      ).order_by(Notification.sent_at.desc()).all()
    """
    return render_template('farmer/notifications.html')


# ══════════════════════════════════════════════════════════════
# PROFILE  —  /farmer/profile
# ══════════════════════════════════════════════════════════════
@farmer_bp.route('/profile', methods=['GET', 'POST'])
@login_required
@farmer_required
def profile():
    """
    Edit name, phone, region, crop, profile photo.

    TODO Sprint 7:
      POST: Validate and update current_user fields.
            db.session.commit()
    """
    return render_template('farmer/profile.html')