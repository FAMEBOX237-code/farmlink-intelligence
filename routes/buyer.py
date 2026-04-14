# ============================================================
# routes/buyer.py
#
# Buyer portal routes — FarmLink Intelligence
#
# Public routes (no login required):
#   GET  /marketplace             — Browse all listings
#   GET  /listings/<id>           — Listing detail
#
# Authenticated buyer routes (@login_required):
#   GET  /buyer/alerts            — My alerts
#   GET  /buyer/notifications     — Notifications
#   GET  /buyer/profile           — Profile & settings
#
# NOTE: The marketplace and listing detail are accessible
# without login — anyone can browse. Login is only needed
# to register alerts or contact farmers.
# ============================================================

from functools import wraps
from flask import Blueprint, render_template, redirect, url_for
from flask_login import login_required, current_user

buyer_bp = Blueprint('buyer', __name__, url_prefix='')


# ── Role guard decorator ──────────────────────────────────────
def buyer_required(f):
    """
    Decorator: ensures the logged-in user is a buyer.
    Use AFTER @login_required.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'buyer':
            return redirect(url_for('public.forbidden_direct'))
        return f(*args, **kwargs)
    return decorated


# ══════════════════════════════════════════════════════════════
# MARKETPLACE  —  /marketplace
# Public — no login required
# ══════════════════════════════════════════════════════════════
@buyer_bp.route('/marketplace')
def marketplace():
    """
    Public marketplace — browse all active listings.
    Accessible without login. Buyers with accounts see
    their saved alert status on each listing.

    TODO Sprint 6:
      listings = ProduceListing.query.filter_by(status='active')\
          .order_by(ProduceListing.created_at.desc()).all()
      Apply filters: crop_type, region, min_quality, min_trust,
      has_forecast — from request.args.
    """
    return render_template('buyer/marketplace.html')


# ══════════════════════════════════════════════════════════════
# LISTING DETAIL  —  /listings/<int:listing_id>
# Public — no login required
# ══════════════════════════════════════════════════════════════
@buyer_bp.route('/listings/<int:listing_id>')
def listing_detail(listing_id):
    """
    Full listing detail page.
    Shows: quality score breakdown, trust score, forecast,
    farmer card, CTA buttons (contact / register alert).

    TODO Sprint 6:
      listing = ProduceListing.query.get_or_404(listing_id)
      Only show if listing.status == 'active'.
    """
    return render_template('buyer/listing_detail.html', listing_id=listing_id)


# ══════════════════════════════════════════════════════════════
# MY ALERTS  —  /buyer/alerts
# Requires login + buyer role
# ══════════════════════════════════════════════════════════════
@buyer_bp.route('/buyer/alerts', methods=['GET', 'POST'])
@login_required
@buyer_required
def alerts():
    """
    Standing alert management: create, edit, remove alerts.
    Tabs: All / Triggered / Watching / Inactive.

    TODO Sprint 8:
      alerts = BuyerAlert.query.filter_by(buyer_id=current_user.id).all()
      POST: Create new BuyerAlert row.
    """
    return render_template('buyer/alerts.html')


# ══════════════════════════════════════════════════════════════
# BUYER NOTIFICATIONS  —  /buyer/notifications
# ══════════════════════════════════════════════════════════════
@buyer_bp.route('/buyer/notifications')
@login_required
@buyer_required
def notifications():
    """
    Notification inbox — harvest alerts, system messages.

    TODO Sprint 8:
      notifications = Notification.query.filter_by(
          recipient_id=current_user.id
      ).order_by(Notification.sent_at.desc()).all()
    """
    return render_template('buyer/notifications.html')


# ══════════════════════════════════════════════════════════════
# BUYER PROFILE  —  /buyer/profile
# ══════════════════════════════════════════════════════════════
@buyer_bp.route('/buyer/profile', methods=['GET', 'POST'])
@login_required
@buyer_required
def profile():
    """
    Edit buyer name, phone, region preferences.

    TODO Sprint 8: POST saves updated user fields.
    """
    return render_template('buyer/profile.html')