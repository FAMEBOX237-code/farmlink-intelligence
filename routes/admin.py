# ============================================================
# routes/admin.py
#
# Admin panel routes — FarmLink Intelligence
#
# All routes require login + admin role.
#
# Routes:
#   GET  /admin/dashboard   — Platform overview
#   GET  /admin/accounts    — Account management
#   GET  /admin/sensors     — Farm & sensor monitor
#   GET  /admin/reports     — Regional reports
#   GET  /admin/notifications — Admin notifications
# ============================================================

from functools import wraps
from flask import Blueprint, render_template, redirect, url_for
from flask_login import login_required, current_user

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


# ── Role guard decorator ──────────────────────────────────────
def admin_required(f):
    """
    Decorator: ensures the logged-in user is an admin.
    Use AFTER @login_required.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            return redirect(url_for('public.forbidden_direct'))
        return f(*args, **kwargs)
    return decorated


# ══════════════════════════════════════════════════════════════
# ADMIN DASHBOARD  —  /admin/dashboard
# ══════════════════════════════════════════════════════════════
@admin_bp.route('/dashboard')
@login_required
@admin_required
def dashboard():
    """
    Platform overview: 8 metric cards, quick actions,
    alerts feed, pending verifications, offline nodes,
    farmers by region chart, activity chart.

    TODO Sprint 9:
      - total_farmers = User.query.filter_by(role='farmer').count()
      - total_buyers  = User.query.filter_by(role='buyer').count()
      - pending       = User.query.filter_by(is_verified=False).count()
      - offline_nodes from Farm where last_reading > 30 min
      - active_listings = ProduceListing.query.filter_by(status='active').count()
    """
    return render_template('admin/dashboard.html')


# ══════════════════════════════════════════════════════════════
# ACCOUNTS MANAGEMENT  —  /admin/accounts
# ══════════════════════════════════════════════════════════════
@admin_bp.route('/accounts', methods=['GET', 'POST'])
@login_required
@admin_required
def accounts():
    """
    Tabs: All / Pending / Farmers / Buyers / Suspended.
    Actions: Verify, Reject, Suspend, Reinstate.

    TODO Sprint 9:
      POST: Handle verify/suspend/reinstate actions.
      users = User.query.all() — filtered by tab.
    """
    return render_template('admin/accounts.html')


# ══════════════════════════════════════════════════════════════
# SENSOR MONITOR  —  /admin/sensors
# ══════════════════════════════════════════════════════════════
@admin_bp.route('/sensors')
@login_required
@admin_required
def sensor_monitor():
    """
    Cameroon map + tabbed node list: Online / Offline / Intermittent.
    Cards show uptime bar, last reading, contact farmer link.

    TODO Sprint 9:
      farms = Farm.query.all()
      For each, compute online/offline from latest SensorReading.
    """
    return render_template('admin/sensor_monitor.html')


# ══════════════════════════════════════════════════════════════
# REPORTS  —  /admin/reports
# ══════════════════════════════════════════════════════════════
@admin_bp.route('/reports')
@login_required
@admin_required
def reports():
    """
    Regional agricultural reports with export options.
    Filters: region, time period, crop type.
    Charts: platform growth, farmers by region, top crops.
    Table: per-region performance.

    TODO Sprint 9:
      Build aggregate queries for each chart.
      Export as PDF/CSV (use reportlab or weasyprint).
    """
    return render_template('admin/reports.html')


# ══════════════════════════════════════════════════════════════
# ADMIN NOTIFICATIONS  —  /admin/notifications
# ══════════════════════════════════════════════════════════════
@admin_bp.route('/notifications')
@login_required
@admin_required
def notifications():
    """
    Admin notification inbox — system alerts, node failures,
    low trust score warnings, pending verifications.

    TODO Sprint 9: Query Notification table for admin recipient.
    """
    return render_template('admin/notifications.html')