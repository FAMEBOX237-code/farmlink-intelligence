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
# ACCOUNTS MANAGEMENT  —  /admin/accounts
# ══════════════════════════════════════════════════════════════
@admin_bp.route('/accounts', methods=['GET', 'POST'])
@login_required
@admin_required
def accounts():
    """
    Tabs: All / Pending / Farmers / Buyers / Suspended.
    POST actions: verify, suspend, reinstate.
    """
    # ── Handle POST actions ───────────────────────────────────
    if request.method == 'POST':
        action  = request.form.get('action')
        user_id = request.form.get('user_id', type=int)
        target  = User.query.get(user_id) if user_id else None

        if target and target.role != 'admin':
            if action == 'verify':
                target.is_verified  = True
                target.is_suspended = False
                db.session.commit()
                flash(f'{target.full_name} has been verified.', 'success')
            elif action == 'suspend':
                target.is_suspended = True
                db.session.commit()
                flash(f'{target.full_name} has been suspended.', 'warning')
            elif action == 'reinstate':
                target.is_suspended = False
                db.session.commit()
                flash(f'{target.full_name} has been reinstated.', 'success')
        return redirect(url_for('admin.accounts', tab=request.form.get('tab', 'all')))

    # ── GET: build tab counts and filtered list ───────────────
    tab = request.args.get('tab', 'all')

    counts = {
        'all':       User.query.filter(User.role != 'admin').count(),
        'pending':   User.query.filter_by(role='farmer', is_verified=False, is_suspended=False).count(),
        'farmers':   User.query.filter_by(role='farmer').count(),
        'buyers':    User.query.filter_by(role='buyer').count(),
        'suspended': User.query.filter_by(is_suspended=True).count(),
    }

    base = User.query.filter(User.role != 'admin')
    if tab == 'pending':
        users = base.filter_by(is_verified=False, is_suspended=False, role='farmer')
    elif tab == 'farmers':
        users = base.filter_by(role='farmer')
    elif tab == 'buyers':
        users = base.filter_by(role='buyer')
    elif tab == 'suspended':
        users = base.filter_by(is_suspended=True)
    else:
        users = base

    # Search
    q = request.args.get('q', '').strip()
    if q:
        users = users.filter(
            (User.full_name.ilike(f'%{q}%')) |
            (User.email.ilike(f'%{q}%'))
        )

    users = users.order_by(User.created_at.desc()).all()

    return render_template(
        'admin/accounts.html',
        admin         = current_user,
        active_page   = 'accounts',
        unread_notifs = _unread_notifs(),
        tab           = tab,
        counts        = counts,
        users         = users,
        search_query  = q,
    )

# ══════════════════════════════════════════════════════════════
# SENSOR MONITOR  —  /admin/sensor_monitor
# ══════════════════════════════════════════════════════════════
@admin_bp.route('/sensor_monitor')
@login_required
@admin_required
def sensor_monitor():
    """
    All farms with sensor status: online / offline / intermittent / no-data.
    Tabs: All / Online / Offline / No Sensor.
    """
    now               = datetime.utcnow()
    offline_threshold = now - timedelta(minutes=60)
    warn_threshold    = now - timedelta(minutes=35)

    tab = request.args.get('tab', 'all')

    farms = Farm.query.order_by(Farm.created_at.desc()).all()

    farm_data   = []
    cnt_online  = 0
    cnt_offline = 0
    cnt_warn    = 0
    cnt_nodata  = 0

    for farm in farms:
        latest = (SensorReading.query
                  .filter_by(farm_id=farm.id)
                  .order_by(SensorReading.timestamp.desc())
                  .first())

        if latest is None:
            status = 'no-data'
            cnt_nodata += 1
            last_seen  = '—'
            uptime_pct = 0
        elif latest.timestamp >= warn_threshold:
            status = 'online'
            cnt_online += 1
            diff       = now - latest.timestamp
            mins       = int(diff.total_seconds() // 60)
            last_seen  = f"{mins}m ago" if mins else "just now"
            uptime_pct = 97
        elif latest.timestamp >= offline_threshold:
            status = 'intermittent'
            cnt_warn += 1
            diff       = now - latest.timestamp
            mins       = int(diff.total_seconds() // 60)
            last_seen  = f"{mins}m ago"
            uptime_pct = 60
        else:
            status = 'offline'
            cnt_offline += 1
            diff       = now - latest.timestamp
            hours      = int(diff.total_seconds() // 3600)
            mins       = int((diff.total_seconds() % 3600) // 60)
            last_seen  = f"{hours}h {mins}m ago" if hours else f"{mins}m ago"
            uptime_pct = 0

        farm_data.append({
            'farm':       farm,
            'owner':      farm.owner,
            'status':     status,
            'last_seen':  last_seen,
            'uptime_pct': uptime_pct,
            'latest':     latest,
        })

    # Filter by tab
    if tab == 'online':
        farm_data = [f for f in farm_data if f['status'] in ('online', 'intermittent')]
    elif tab == 'offline':
        farm_data = [f for f in farm_data if f['status'] == 'offline']
    elif tab == 'no_sensor':
        farm_data = [f for f in farm_data if f['status'] == 'no-data']

    return render_template(
        'admin/sensor_monitor.html',
        admin         = current_user,
        active_page   = 'sensor_monitor',
        unread_notifs = _unread_notifs(),
        tab           = tab,
        farm_data     = farm_data,
        cnt_online    = cnt_online,
        cnt_offline   = cnt_offline,
        cnt_warn      = cnt_warn,
        cnt_nodata    = cnt_nodata,
        total_nodes   = len(farms),
    )

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
