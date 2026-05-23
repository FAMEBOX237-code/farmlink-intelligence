# ============================================================
# routes/admin.py — FarmLink Intelligence
#
# Admin panel routes.
# All routes require login + admin role.
#
# Routes:
#   GET  /admin/dashboard      — Platform overview
#   GET  /admin/accounts       — Account management
#   POST /admin/accounts       — Verify / suspend / reinstate
#   GET  /admin/sensor_monitor — Farm & sensor monitor
#   GET  /admin/reports        — Regional reports
#   GET  /admin/notifications  — Admin notifications
#   POST /admin/notifications  — Mark all read
# ============================================================

from functools import wraps
from datetime import datetime, timedelta

from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from sqlalchemy import func

from extensions import db
from models.models import (
    User, Farm, SensorReading, HarvestForecast,
    ProduceListing, Transaction, Notification
)

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


# ── Role guard ────────────────────────────────────────────────
def admin_required(f):
    """Ensures the logged-in user is an admin. Use AFTER @login_required."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_#user.is_authenticated or current_user.role != 'admin':
            return redirect(url_for('public.forbidden_direct'))
        return f(*args, **kwargs)
    return decorated


# ── Shared helper: unread notifications count for topbar ─────
def _unread_notifs():
    try:
        return Notification.query.filter_by(
            recipient_id=current_user.id,
            is_read=False
        ).count()
    except Exception:
        return 0

# ══════════════════════════════════════════════════════════════
# REPORTS  —  /admin/reports
# ══════════════════════════════════════════════════════════════
@admin_bp.route('/reports')
@login_required
@admin_required
def reports():
    """
    Regional agricultural reports.
    Filters: region, time period, crop type.
    """
    # Aggregate listings by region
    region_data = (
        db.session.query(
            Farm.region,
            func.count(ProduceListing.id).label('listing_count'),
            func.count(func.distinct(ProduceListing.farmer_id)).label('farmer_count'),
            func.sum(ProduceListing.quantity_kg).label('total_kg'),
            func.avg(ProduceListing.quality_score_live).label('avg_quality'),
        )
        .join(ProduceListing, ProduceListing.farm_id == Farm.id, isouter=True)
        .group_by(Farm.region)
        .order_by(func.count(ProduceListing.id).desc())
        .all()
    )

    # Top crop types
    crop_data = (
        db.session.query(
            ProduceListing.crop_type,
            func.count(ProduceListing.id).label('count'),
            func.avg(ProduceListing.quality_score_live).label('avg_quality'),
        )
        .filter(ProduceListing.status == 'active')
        .group_by(ProduceListing.crop_type)
        .order_by(func.count(ProduceListing.id).desc())
        .limit(10)
        .all()
    )

    # Summary stats
    total_farmers   = User.query.filter_by(role='farmer').count()
    total_buyers    = User.query.filter_by(role='buyer').count()
    active_listings = ProduceListing.query.filter_by(status='active').count()
    total_txns      = Transaction.query.filter_by(status='completed').count()

    # Max listing count for bar widths
    max_listings = max((r.listing_count for r in region_data), default=1) or 1

    return render_template(
        'admin/reports.html',
        admin          = current_user,
        active_page    = 'reports',
        unread_notifs  = _unread_notifs(),
        region_data    = region_data,
        crop_data      = crop_data,
        total_farmers  = total_farmers,
        total_buyers   = total_buyers,
        active_listings= active_listings,
        total_txns     = total_txns,
        max_listings   = max_listings,
    )


# ══════════════════════════════════════════════════════════════
# ADMIN NOTIFICATIONS  —  /admin/notifications
# ══════════════════════════════════════════════════════════════
@admin_bp.route('/notifications', methods=['GET', 'POST'])
@login_required
@admin_required
def notifications():
    """
    Admin notification inbox.
    POST: mark_all_read action.
    """
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'mark_all_read':
            Notification.query.filter_by(
                recipient_id=current_user.id, is_read=False
            ).update({'is_read': True}, synchronize_session=False)
            db.session.commit()
            flash('All notifications marked as read.', 'success')
        return redirect(url_for('admin.notifications'))

    tab = request.args.get('tab', 'all')

    base_q = Notification.query.filter_by(recipient_id=current_user.id)

    counts = {
        'all':    Notification.query.filter_by(recipient_id=current_user.id).count(),
        'unread': Notification.query.filter_by(recipient_id=current_user.id, is_read=False).count(),
        'system': Notification.query.filter_by(recipient_id=current_user.id, type='system').count(),
        'sensor': Notification.query.filter_by(recipient_id=current_user.id, type='sensor_offline').count(),
    }

    if tab == 'unread':
        notifs = base_q.filter_by(is_read=False)
    elif tab == 'system':
        notifs = base_q.filter_by(type='system')
    elif tab == 'sensor':
        notifs = base_q.filter_by(type='sensor_offline')
    else:
        notifs = base_q

    notifs = notifs.order_by(Notification.sent_at.desc()).all()

    return render_template(
        'admin/notifications.html',
        admin         = current_user,
        active_page   = 'notifications',
        unread_notifs = _unread_notifs(),
        tab           = tab,
        counts        = counts,
        notifs        = notifs,
    )