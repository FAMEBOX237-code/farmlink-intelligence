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
from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from models.models import ProduceListing, User, Farm, HarvestForecast, BuyerAlert
from sqlalchemy import or_

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
    Accessible without login.

    Filters (all optional, from URL params):
      crop        — crop type substring match
      region      — exact region match
      min_quality — minimum quality score (int)
      min_trust   — minimum trust score (float)
      forecast    — '1' to show only listings with forecasts
      sort        — 'newest'|'quality'|'price_asc'|'price_desc'|'trust'
    """
    # ── Read filter params ────────────────────────────────────
    crop_filter    = request.args.get('crop',        '').strip()
    region_filter  = request.args.get('region',      '').strip()
    sort_by        = request.args.get('sort',        'newest')
    min_quality    = request.args.get('min_quality', '', type=str).strip()
    has_forecast   = request.args.get('forecast',    '')

    # ── Base query — active listings only ─────────────────────
    q = ProduceListing.query.filter_by(status='active')

    # ── Apply filters ─────────────────────────────────────────
    if crop_filter:
        q = q.filter(ProduceListing.crop_type.ilike(f'%{crop_filter}%'))

    if region_filter:
        q = q.join(Farm, ProduceListing.farm_id == Farm.id)\
              .filter(Farm.region == region_filter)

    if min_quality:
        try:
            q = q.filter(ProduceListing.quality_score_live >= int(min_quality))
        except ValueError:
            pass

    if has_forecast == '1':
        q = q.filter(ProduceListing.forecast_id.isnot(None))

    # ── Sorting ───────────────────────────────────────────────
    if sort_by == 'quality':
        q = q.order_by(ProduceListing.quality_score_live.desc())
    elif sort_by == 'price_asc':
        q = q.order_by(ProduceListing.price_per_kg.asc())
    elif sort_by == 'price_desc':
        q = q.order_by(ProduceListing.price_per_kg.desc())
    elif sort_by == 'trust':
        q = q.join(User, ProduceListing.farmer_id == User.id)\
              .order_by(User.trust_score.desc())
    else:
        q = q.order_by(ProduceListing.created_at.desc())

    listings = q.all()
    total_count = len(listings)

    # ── Build display dicts ───────────────────────────────────
    # Pre-compute everything the template needs so template stays clean
    listings_display = []
    for lst in listings:
        farmer = User.query.get(lst.farmer_id)
        farm   = Farm.query.get(lst.farm_id)
        if not farmer or not farm:
            continue

        q_score = lst.quality_score_live or 0
        if q_score >= 75:
            q_css = 'high'
        elif q_score >= 50:
            q_css = 'medium'
        else:
            q_css = 'low'

        trust = float(farmer.trust_score or 0)

        listings_display.append({
            'id'          : lst.id,
            'crop'        : lst.crop_type,
            'quantity'    : float(lst.quantity_kg),
            'price'       : float(lst.price_per_kg),
            'min_order'   : float(lst.min_order_kg) if lst.min_order_kg else None,
            'q_live'      : q_score,
            'q_css'       : q_css,
            'trust'       : round(trust, 1),
            'has_forecast': lst.forecast_id is not None,
            'photo_url'   : lst.photo_url,
            'description' : lst.description or '',
            'farm_name'   : farm.name,
            'farm_region' : farm.region,
            'farm_town'   : farm.town or '',
            'farmer_name' : farmer.full_name,
            'farmer_id'   : farmer.id,
            'farmer_initials': (farmer.full_name[:2].upper()
                                if farmer.full_name else '??'),
            'created_at'  : lst.created_at,
            'inquiry_count': lst.inquiry_count or 0,
        })

    # ── Distinct regions for filter dropdown ──────────────────
    regions = [r[0] for r in
               Farm.query.with_entities(Farm.region)
                         .distinct()
                         .order_by(Farm.region)
                         .all()
               if r[0]]

    # ── Unread notifs for sidebar (logged-in buyer only) ──────
    unread_notifs = 0
    active_alerts = 0
    if current_user.is_authenticated and current_user.is_buyer():
        from models.models import Notification
        unread_notifs = Notification.query.filter_by(
            recipient_id=current_user.id, is_read=False).count()
        active_alerts = BuyerAlert.query.filter_by(
            buyer_id=current_user.id, is_active=True).count()

    return render_template(
        'buyer/marketplace.html',
        listings_display = listings_display,
        total_count      = total_count,
        crop_filter      = crop_filter,
        region_filter    = region_filter,
        sort_by          = sort_by,
        min_quality      = min_quality,
        has_forecast     = has_forecast,
        regions          = regions,
        active_nav       = 'marketplace',
        unread_notifs    = unread_notifs,
        active_alerts    = active_alerts,
        active_page      = 'marketplace',
    )


# ══════════════════════════════════════════════════════════════
# LISTING DETAIL  —  /listings/<int:listing_id>
# Public — no login required
# ══════════════════════════════════════════════════════════════
@buyer_bp.route('/listings/<int:listing_id>')
def listing_detail(listing_id):
    """
    Full listing detail page.
    Public — no login required.
    Shows: photo, quality score breakdown, live sensor data,
    harvest forecast, farmer card with trust score,
    CTA buttons (contact farmer / register pre-order alert).
    """
    from models.models import (ProduceListing, Farm, HarvestForecast,
                               SensorReading, Rating, Notification)
    from datetime import date

    # ── Fetch listing — 404 if missing or not active ──────────
    listing = ProduceListing.query.get_or_404(listing_id)
    if listing.status not in ('active',):
        from flask import abort
        abort(404)

    farmer = User.query.get_or_404(listing.farmer_id)
    farm   = Farm.query.get_or_404(listing.farm_id)

    # ── Quality score details ─────────────────────────────────
    q_live = listing.quality_score_live or 0
    q_lock = listing.quality_score_at_listing or 0
    if q_live >= 75:
        q_css = 'high'
    elif q_live >= 50:
        q_css = 'medium'
    else:
        q_css = 'low'

    # ── Latest sensor reading ─────────────────────────────────
    latest_reading = (SensorReading.query
                      .filter_by(farm_id=farm.id)
                      .order_by(SensorReading.timestamp.desc())
                      .first())

    sensor = None
    if latest_reading:
        sensor = {
            'soil_moisture'  : float(latest_reading.soil_moisture or 0),
            'temperature'    : float(latest_reading.temperature   or 0),
            'humidity'       : float(latest_reading.humidity      or 0),
            'light_intensity': float(latest_reading.light_intensity or 0),
            'is_raining'     : latest_reading.is_raining,
            'timestamp'      : latest_reading.timestamp,
        }

    # ── Total sensor readings on this farm ────────────────────
    total_readings = SensorReading.query.filter_by(farm_id=farm.id).count()

    # ── Harvest forecast ──────────────────────────────────────
    forecast = None
    if listing.forecast_id:
        fc = HarvestForecast.query.get(listing.forecast_id)
        if fc and fc.is_active:
            today = date.today()
            days_to_start = (fc.predicted_harvest_start - today).days
            days_to_end   = (fc.predicted_harvest_end   - today).days
            confidence    = int(fc.confidence_score or 0)
            if confidence >= 75:
                conf_css = 'high'
            elif confidence >= 50:
                conf_css = 'medium'
            else:
                conf_css = 'low'
            forecast = {
                'start'        : fc.predicted_harvest_start,
                'end'          : fc.predicted_harvest_end,
                'days_to_start': days_to_start,
                'days_to_end'  : days_to_end,
                'confidence'   : confidence,
                'conf_css'     : conf_css,
                'data_points'  : fc.data_points_used or 0,
                'buyers_alerted': fc.buyers_alerted or 0,
                'window_label' : (
                    fc.predicted_harvest_start.strftime('%d %b %Y') +
                    ' – ' +
                    fc.predicted_harvest_end.strftime('%d %b %Y')
                ),
            }

    # ── Farmer trust score ────────────────────────────────────
    trust_raw  = float(farmer.trust_score or 0)
    trust_pct  = min(round(trust_raw / 5.0 * 100), 100)
    if trust_raw >= 4.0:
        trust_css = 'high'
    elif trust_raw >= 2.5:
        trust_css = 'medium'
    else:
        trust_css = 'low'

    # ── Farmer ratings summary ────────────────────────────────
    ratings = Rating.query.filter_by(farmer_id=farmer.id).all()
    rating_count = len(ratings)
    avg_rating   = round(sum(r.score for r in ratings) / rating_count, 1) if ratings else 0

    # ── Other active listings by this farmer ──────────────────
    other_listings = (ProduceListing.query
                      .filter_by(farmer_id=farmer.id, status='active')
                      .filter(ProduceListing.id != listing.id)
                      .order_by(ProduceListing.created_at.desc())
                      .limit(3)
                      .all())

    # ── Logged-in buyer context ───────────────────────────────
    unread_notifs = 0
    active_alerts = 0
    if current_user.is_authenticated and current_user.is_buyer():
        unread_notifs = Notification.query.filter_by(
            recipient_id=current_user.id, is_read=False).count()
        active_alerts = BuyerAlert.query.filter_by(
            buyer_id=current_user.id, is_active=True).count()

    return render_template(
        'buyer/listing_detail.html',
        listing        = listing,
        farmer         = farmer,
        farm           = farm,
        q_live         = q_live,
        q_lock         = q_lock,
        q_css          = q_css,
        sensor         = sensor,
        total_readings = total_readings,
        forecast       = forecast,
        trust_raw      = round(trust_raw, 1),
        trust_pct      = trust_pct,
        trust_css      = trust_css,
        rating_count   = rating_count,
        avg_rating     = avg_rating,
        other_listings = other_listings,
        unread_notifs  = unread_notifs,
        active_alerts  = active_alerts,
        active_page    = 'marketplace',
        active_nav     = 'marketplace',
    )


# ══════════════════════════════════════════════════════════════
# MY ALERTS  —  /buyer/alerts
# Requires login + buyer role
# ══════════════════════════════════════════════════════════════
@buyer_bp.route('/buyer/alerts', methods=['GET', 'POST'])
@login_required
@buyer_required
def alerts():
    """
    Standing pre-order alert management.
    GET  — show all alerts with tab counts.
    POST — create new alert / toggle active / delete.

    Actions (hidden field 'action'):
      create  — new BuyerAlert row
      toggle  — flip is_active on existing alert
      delete  — remove alert permanently
    """
    from models.models import BuyerAlert, Notification, Farm

    # ── POST — handle form actions ────────────────────────────
    if request.method == 'POST':
        action = request.form.get('action', '')

        if action == 'create':
            produce_type  = request.form.get('produce_type', '').strip()
            region        = request.form.get('region', '').strip()
            min_quality   = request.form.get('min_quality_score', 0, type=int)
            min_trust     = request.form.get('min_trust_score', 0.0, type=float)
            min_qty       = request.form.get('min_quantity_kg', 0.0, type=float)

            if not produce_type or not region:
                flash('Crop type and region are required.', 'error')
            else:
                # Prevent duplicate active alerts for same crop+region
                existing = BuyerAlert.query.filter_by(
                    buyer_id=current_user.id,
                    produce_type=produce_type,
                    region=region,
                    is_active=True
                ).first()
                if existing:
                    flash(
                        f'You already have an active alert for '
                        f'{produce_type} in {region}.', 'warning'
                    )
                else:
                    from extensions import db
                    new_alert = BuyerAlert(
                        buyer_id         = current_user.id,
                        produce_type     = produce_type,
                        region           = region,
                        min_quality_score= min_quality,
                        min_trust_score  = min_trust,
                        min_quantity_kg  = min_qty,
                        is_active        = True,
                    )
                    db.session.add(new_alert)
                    db.session.commit()
                    flash(
                        f'Alert created — you\'ll be notified when '
                        f'{produce_type} from {region} is ready.', 'success'
                    )

        elif action == 'toggle':
            alert_id = request.form.get('alert_id', type=int)
            alert = BuyerAlert.query.filter_by(
                id=alert_id, buyer_id=current_user.id).first()
            if alert:
                from extensions import db
                alert.is_active = not alert.is_active
                db.session.commit()
                state = 'activated' if alert.is_active else 'paused'
                flash(f'Alert {state}.', 'success')

        elif action == 'delete':
            alert_id = request.form.get('alert_id', type=int)
            alert = BuyerAlert.query.filter_by(
                id=alert_id, buyer_id=current_user.id).first()
            if alert:
                from extensions import db
                db.session.delete(alert)
                db.session.commit()
                flash('Alert deleted.', 'success')

        return redirect(url_for('buyer.alerts'))

    # ── GET — build page context ──────────────────────────────
    all_alerts = (BuyerAlert.query
                  .filter_by(buyer_id=current_user.id)
                  .order_by(BuyerAlert.created_at.desc())
                  .all())

    # Tab counts
    active_count   = sum(1 for a in all_alerts if a.is_active and a.triggered_count == 0)
    triggered_count= sum(1 for a in all_alerts if a.triggered_count > 0)
    inactive_count = sum(1 for a in all_alerts if not a.is_active)

    # Active tab from URL param
    active_tab = request.args.get('tab', 'all')

    # Filter by tab
    if active_tab == 'triggered':
        display_alerts = [a for a in all_alerts if a.triggered_count > 0]
    elif active_tab == 'watching':
        display_alerts = [a for a in all_alerts if a.is_active and a.triggered_count == 0]
    elif active_tab == 'inactive':
        display_alerts = [a for a in all_alerts if not a.is_active]
    else:
        display_alerts = all_alerts

    # Distinct regions for form dropdown
    regions = [r[0] for r in
               Farm.query.with_entities(Farm.region)
               .distinct().order_by(Farm.region).all()
               if r[0]]

    # Sidebar counts
    unread_notifs = Notification.query.filter_by(
        recipient_id=current_user.id, is_read=False).count()
    active_alerts_count = sum(1 for a in all_alerts if a.is_active)

    return render_template(
        'buyer/alerts.html',
        all_alerts       = all_alerts,
        display_alerts   = display_alerts,
        active_tab       = active_tab,
        all_count        = len(all_alerts),
        active_count     = active_count,
        triggered_count  = triggered_count,
        inactive_count   = inactive_count,
        regions          = regions,
        unread_notifs    = unread_notifs,
        active_alerts    = active_alerts_count,
        active_page      = 'alerts',
    )


# ══════════════════════════════════════════════════════════════
# BUYER NOTIFICATIONS  —  /buyer/notifications
# ══════════════════════════════════════════════════════════════
@buyer_bp.route('/buyer/notifications')
@login_required
@buyer_required
def notifications():
    """
    Notification inbox — all notifications for this buyer.
    GET  — render inbox with tab filter.
    POST — mark as read / mark all read / delete one.

    Tabs: All / Unread / Harvest / System
    """
    from models.models import Notification, BuyerAlert
    from extensions import db

    # ── POST actions ──────────────────────────────────────────
    if request.method == 'POST':
        action = request.form.get('action', '')

        if action == 'mark_read':
            notif_id = request.form.get('notif_id', type=int)
            n = Notification.query.filter_by(
                id=notif_id, recipient_id=current_user.id).first()
            if n:
                n.is_read = True
                db.session.commit()

        elif action == 'mark_all_read':
            Notification.query.filter_by(
                recipient_id=current_user.id,
                is_read=False
            ).update({'is_read': True})
            db.session.commit()
            flash('All notifications marked as read.', 'success')

        elif action == 'delete':
            notif_id = request.form.get('notif_id', type=int)
            n = Notification.query.filter_by(
                id=notif_id, recipient_id=current_user.id).first()
            if n:
                db.session.delete(n)
                db.session.commit()

        return redirect(url_for('buyer.notifications',
                                tab=request.form.get('current_tab', 'all')))

    # ── GET — build context ───────────────────────────────────
    active_tab = request.args.get('tab', 'all')

    # Mark individual notification read if id in URL
    read_id = request.args.get('read', type=int)
    if read_id:
        n = Notification.query.filter_by(
            id=read_id, recipient_id=current_user.id).first()
        if n and not n.is_read:
            n.is_read = True
            db.session.commit()

    # All notifications newest first
    all_notifs = (Notification.query
                  .filter_by(recipient_id=current_user.id)
                  .order_by(Notification.sent_at.desc())
                  .all())

    # Tab counts
    tab_counts = {
        'all'     : len(all_notifs),
        'unread'  : sum(1 for n in all_notifs if not n.is_read),
        'harvest' : sum(1 for n in all_notifs if n.type == 'harvest_alert'),
        'system'  : sum(1 for n in all_notifs
                        if n.type in ('system', 'account_verified',
                                      'account_suspended')),
    }

    # Filter by tab
    if active_tab == 'unread':
        display_notifs = [n for n in all_notifs if not n.is_read]
    elif active_tab == 'harvest':
        display_notifs = [n for n in all_notifs if n.type == 'harvest_alert']
    elif active_tab == 'system':
        display_notifs = [n for n in all_notifs
                          if n.type in ('system', 'account_verified',
                                        'account_suspended')]
    else:
        display_notifs = all_notifs

    # Build display dicts — pre-compute icon, colour, action link
    TYPE_META = {
        'harvest_alert'       : ('amber', 'Harvest forecast'),
        'sensor_offline'      : ('gray',  'Sensor offline'),
        'quality_change'      : ('teal',  'Quality update'),
        'account_verified'    : ('teal',  'Account verified'),
        'account_suspended'   : ('red',   'Account suspended'),
        'listing_published'   : ('green', 'Listing published'),
        'transaction_completed': ('green','Transaction complete'),
        'buyer_enquiry'       : ('blue',  'Buyer enquiry'),
        'system'              : ('gray',  'System'),
    }

    notifs_display = []
    for n in display_notifs:
        colour, type_label = TYPE_META.get(n.type, ('gray', 'Notification'))

        # Action URL — link to listing if available
        if n.listing_id:
            action_url   = url_for('buyer.listing_detail',
                                   listing_id=n.listing_id)
            action_label = 'View listing'
        elif n.forecast_id:
            action_url   = url_for('buyer.marketplace')
            action_label = 'Browse marketplace'
        else:
            action_url   = None
            action_label = None

        # Time display
        from datetime import datetime, timezone
        now  = datetime.utcnow()
        diff = now - n.sent_at
        if diff.days >= 7:
            time_display = n.sent_at.strftime('%d %b %Y')
        elif diff.days >= 1:
            time_display = f'{diff.days}d ago'
        elif diff.seconds >= 3600:
            time_display = f'{diff.seconds // 3600}h ago'
        elif diff.seconds >= 60:
            time_display = f'{diff.seconds // 60}m ago'
        else:
            time_display = 'Just now'

        notifs_display.append({
            'id'          : n.id,
            'type'        : n.type,
            'type_label'  : type_label,
            'colour'      : colour,
            'title'       : n.title,
            'message'     : n.message,
            'is_read'     : n.is_read,
            'channel'     : n.channel,
            'sent_at'     : n.sent_at,
            'time_display': time_display,
            'action_url'  : action_url,
            'action_label': action_label,
        })

    # Sidebar counts
    unread_notifs  = tab_counts['unread']
    active_alerts  = BuyerAlert.query.filter_by(
        buyer_id=current_user.id, is_active=True).count()

    return render_template(
        'buyer/notifications.html',
        notifs_display = notifs_display,
        active_tab     = active_tab,
        tab_counts     = tab_counts,
        unread_notifs  = unread_notifs,
        active_alerts  = active_alerts,
        active_page    = 'notifications',
    )


# ══════════════════════════════════════════════════════════════
# BUYER PROFILE  —  /buyer/profile
# ══════════════════════════════════════════════════════════════
@buyer_bp.route('/buyer/profile', methods=['GET', 'POST'])
@login_required
@buyer_required
def profile():
    """
    Buyer profile — own view.
    Tabs: info (edit details + photo) | security (password) | danger zone

    GET  — render profile with active tab.
    POST — handle actions: update_photo, update_info,
           change_password, delete_account
    """
    from models.models import BuyerAlert, Notification, ProduceListing
    from extensions import db
    from werkzeug.security import check_password_hash, generate_password_hash
    from flask import current_app
    from routes.farmer import _REGIONS
    import os

    u = current_user  # shorthand — same User object throughout

    # ── Shared sidebar counts ─────────────────────────────────
    unread_notifs = Notification.query.filter_by(
        recipient_id=u.id, is_read=False).count()
    active_alerts = BuyerAlert.query.filter_by(
        buyer_id=u.id, is_active=True).count()

    # ── Shared profile stats ──────────────────────────────────
    total_alerts   = BuyerAlert.query.filter_by(buyer_id=u.id).count()
    member_since   = u.created_at.strftime('%B %Y')

    def _ctx():
        return dict(
            unread_notifs  = unread_notifs,
            active_alerts  = active_alerts,
            total_alerts   = total_alerts,
            member_since   = member_since,
            regions        = _REGIONS,
            form_errors    = None,
            form_data      = None,
            active_page    = 'profile',
        )

    # ── POST ─────────────────────────────────────────────────
    if request.method == 'POST':
        action = request.form.get('action', '')
        tab    = request.form.get('current_tab', 'info')

        # ── remove_photo ──────────────────────────────────────
        if action == 'remove_photo':
            if u.profile_photo_url:
                old_path = os.path.join(
                    current_app.config.get(
                        'UPLOAD_FOLDER',
                        os.path.join(current_app.root_path, 'static', 'uploads')
                    ),
                    os.path.basename(u.profile_photo_url)
                )
                if os.path.exists(old_path):
                    os.remove(old_path)
                u.profile_photo_url = None
                db.session.commit()
                flash('Profile photo removed.', 'success')
            return redirect(url_for('buyer.profile') + '?tab=info')

        # ── update_photo ──────────────────────────────────────
        if action == 'update_photo':
            photo_file = request.files.get('profile_photo')
            if not photo_file or not photo_file.filename:
                flash('No file selected. Please choose an image.', 'error')
                return redirect(url_for('buyer.profile') + '?tab=info')

            allowed = {'jpg', 'jpeg', 'png', 'webp'}
            ext = (photo_file.filename.rsplit('.', 1)[-1].lower()
                   if '.' in photo_file.filename else '')
            if ext not in allowed:
                flash('Only JPG, PNG, or WEBP images are allowed.', 'error')
                return redirect(url_for('buyer.profile') + '?tab=info')

            # Delete old photo
            if u.profile_photo_url:
                old_path = os.path.join(
                    current_app.config.get(
                        'UPLOAD_FOLDER',
                        os.path.join(current_app.root_path, 'static', 'uploads')
                    ),
                    os.path.basename(u.profile_photo_url)
                )
                if os.path.exists(old_path):
                    os.remove(old_path)

            # Save new photo
            from routes.farmer import _save_photo
            photo_url = _save_photo(photo_file)
            if not photo_url:
                flash('Could not save image. Please try again.', 'error')
                return redirect(url_for('buyer.profile') + '?tab=info')

            u.profile_photo_url = photo_url
            db.session.commit()
            flash('Profile photo updated.', 'success')
            return redirect(url_for('buyer.profile') + '?tab=info')

        # ── update_info ───────────────────────────────────────
        elif action == 'update_info':
            errors = {}
            first  = request.form.get('first_name', '').strip()
            last   = request.form.get('last_name',  '').strip()
            email  = request.form.get('email',      '').strip()
            phone  = request.form.get('phone',      '').strip() or None
            region = request.form.get('region',     '').strip()

            if not first:
                errors['first_name'] = 'First name is required.'
            if not last:
                errors['last_name'] = 'Last name is required.'
            if not email:
                errors['email'] = 'Email address is required.'
            elif email != u.email:
                clash = User.query.filter_by(email=email).first()
                if clash and clash.id != u.id:
                    errors['email'] = 'That email is already in use.'

            if errors:
                return render_template(
                    'buyer/profile.html',
                    active_tab = 'info',
                    form_errors = errors,
                    form_data   = request.form,
                    **_ctx()
                )

            u.full_name = f'{first} {last}'
            u.email     = email
            u.phone     = phone
            u.region    = region if region in _REGIONS else u.region
            db.session.commit()
            flash('Profile updated successfully.', 'success')
            return redirect(url_for('buyer.profile') + '?tab=info')

        # ── change_password ───────────────────────────────────
        elif action == 'change_password':
            errors  = {}
            cur_pw  = request.form.get('current_password', '')
            new_pw  = request.form.get('new_password',     '')
            conf_pw = request.form.get('confirm_password', '')

            if not check_password_hash(u.password_hash, cur_pw):
                errors['current_password'] = 'Current password is incorrect.'
            if len(new_pw) < 8:
                errors['new_password'] = 'Password must be at least 8 characters.'
            if new_pw != conf_pw:
                errors['confirm_password'] = 'Passwords do not match.'

            if errors:
                return render_template(
                    'buyer/profile.html',
                    active_tab  = 'security',
                    form_errors = errors,
                    form_data   = request.form,
                    **_ctx()
                )

            u.password_hash = generate_password_hash(new_pw)
            db.session.commit()
            flash('Password updated successfully.', 'success')
            return redirect(url_for('buyer.profile') + '?tab=security')

        # ── delete_account ────────────────────────────────────
        elif action == 'delete_account':
            confirm = request.form.get('confirm_delete', '').strip()
            if confirm.lower() != 'delete my account':
                flash(
                    'Type "delete my account" exactly to confirm.', 'error'
                )
                return redirect(url_for('buyer.profile') + '?tab=danger')
            from flask_login import logout_user
            db.session.delete(u)
            db.session.commit()
            logout_user()
            flash('Your account has been permanently deleted.', 'success')
            return redirect(url_for('public.landing'))

    # ── GET ───────────────────────────────────────────────────
    tab = request.args.get('tab', 'info')
    return render_template(
        'buyer/profile.html',
        active_tab = tab,
        **_ctx()
    )