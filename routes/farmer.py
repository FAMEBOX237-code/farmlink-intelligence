# ============================================================
# routes/farmer.py — FarmLink Intelligence
#
# ALL computation lives in services/. Templates receive only
# strings, ints, booleans, and pre-built dicts/lists.
# Zero ORM queries or math logic in any template.
#
# Sprint 2 complete:
#   dashboard()       DB-connected, fully pre-computed context
#   farms()           DB-connected, fully pre-computed context
#   add_farm()        GET + POST (creates Farm row)
#   edit_farm()       GET + POST (updates Farm row)
#   delete_farm()     POST (deletes Farm, owner-verified)
#   listings()        DB-connected, tabbed + filtered
#   new_listing()     GET + POST (creates ProduceListing)
#   edit_listing()    GET + POST (updates ProduceListing)
#   forecasts()       redirect to active forecast or empty state
#   forecast_detail() full forecast breakdown (via forecast_engine)
#   trust_score()     full trust breakdown (via trust_engine)
# ============================================================

from functools import wraps
from datetime  import datetime
import os
import uuid

from flask import (
    Blueprint, render_template, redirect,
    url_for, request, flash, current_app
)
from flask_login import login_required, logout_user, current_user
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash, generate_password_hash

from extensions  import db
from models.models import (
    Farm, SensorReading, HarvestForecast,
    ProduceListing, Notification, Transaction,
    Rating, ContactRequest, User,
)
from services.quality_engine   import (
    sensor_status, sensor_status_label,
    quality_detail, sensor_rows, sensor_cells,
)
from services.trust_engine     import trust_display, compute_trust_context
from services.forecast_engine  import compute_forecast_context
from services.alert_dispatcher import build_alerts_display

farmer_bp = Blueprint('farmer', __name__, url_prefix='/farmer')

# ── Constants ─────────────────────────────────────────────────

_REGIONS = [
    'Centre', 'West', 'Littoral', 'North West', 'South West',
    'Adamawa', 'North', 'Far North', 'East', 'South',
]

_CROPS = [
    'Tomatoes', 'Maize', 'Plantains', 'Cassava', 'Yams',
    'Sweet potatoes', 'Groundnuts', 'Beans', 'Pepper', 'Cocoa',
    'Coffee', 'Palm oil', 'Mixed crops', 'Other',
]


# ── Role guard ────────────────────────────────────────────────

def farmer_required(f):
    @wraps(f)
    def d(*a, **kw):
        if not current_user.is_authenticated or current_user.role != 'farmer':
            return redirect(url_for('public.forbidden_direct'))
        return f(*a, **kw)
    return d


# ── Private helpers ───────────────────────────────────────────

def _ago(dt):
    """Human-readable time since dt (UTC)."""
    if not dt:
        return 'never'
    s = (datetime.utcnow() - dt).total_seconds()
    if s < 60:     return 'just now'
    if s < 3600:   m = int(s // 60);   return f'{m} minute{"s" if m != 1 else ""} ago'
    if s < 86400:  h = int(s // 3600); return f'{h} hour{"s" if h != 1 else ""} ago'
    if s < 172800: return 'yesterday'
    return f'{int(s // 86400)} days ago'


def _farms_summary(farms_data):
    """Pre-compute the three summary numbers for the My Farms strip."""
    total  = len(farms_data)
    online = sum(1 for fd in farms_data if fd['sensor_status'] == 'online')
    scores = [fd['quality_score_int'] for fd in farms_data if fd['quality_score_int']]
    avg_q  = round(sum(scores) / len(scores)) if scores else None
    return {'total': total, 'online': online, 'avg_quality': avg_q}


def _sidebar(u):
    """Unread notifications + unread enquiries + active forecast for sidebar."""
    unread = Notification.query.filter_by(recipient_id=u.id, is_read=False).count()
    unread_enq = ContactRequest.query.filter_by(
        recipient_id=u.id, status='sent'
    ).count()
    fc = (HarvestForecast.query
          .join(Farm, Farm.id == HarvestForecast.farm_id)
          .filter(Farm.owner_id == u.id, HarvestForecast.is_active == True)
          .order_by(HarvestForecast.created_at.desc())
          .first())
    return dict(
        unread_notifs    = unread,
        unread_enquiries = unread_enq,
        active_forecast  = fc,
    )


def _f(v):
    """Safe float parse — returns None on failure."""
    try:
        return float(v) if v and str(v).strip() else None
    except (ValueError, TypeError):
        return None


def _save_photo(file_storage):
    """
    Save an uploaded listing photo to static/uploads/.
    Returns the relative URL path e.g. 'uploads/abc123.jpg'
    or None when no valid file was submitted.
    """
    if not file_storage or not file_storage.filename:
        return None
    filename = secure_filename(file_storage.filename)
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext not in {'jpg', 'jpeg', 'png', 'webp'}:
        return None
    unique_name = f"{uuid.uuid4().hex}.{ext}"
    upload_dir  = current_app.config.get(
        'UPLOAD_FOLDER',
        os.path.join(current_app.root_path, 'static', 'uploads')
    )
    os.makedirs(upload_dir, exist_ok=True)
    file_storage.save(os.path.join(upload_dir, unique_name))
    return f"uploads/{unique_name}"


# ══════════════════════════════════════════════════════════════
# DASHBOARD
# ══════════════════════════════════════════════════════════════

@farmer_bp.route('/dashboard')
@login_required
@farmer_required
def dashboard():
    f     = current_user
    now   = datetime.utcnow()
    farms = Farm.query.filter_by(owner_id=f.id).order_by(Farm.created_at).all()

    fid = request.args.get('farm_id', type=int)
    sf  = (Farm.query.filter_by(id=fid, owner_id=f.id).first() if fid else None) \
          or (farms[0] if farms else None)

    lr  = (SensorReading.query.filter_by(farm_id=sf.id)
           .order_by(SensorReading.timestamp.desc()).first()
           if sf else None)

    ss  = sensor_status(lr)
    ago = _ago(lr.timestamp) if lr else 'never'
    qs  = sf.current_quality_score if sf else None
    qd  = quality_detail(lr)
    sr  = sensor_rows(lr)
    ts_display, ts_css = trust_display(f)

    afc = (HarvestForecast.query
           .filter_by(farm_id=sf.id, is_active=True)
           .order_by(HarvestForecast.created_at.desc()).first()
           if sf else None)

    harvest_days = None
    if afc and afc.predicted_harvest_start:
        delta = (afc.predicted_harvest_start - now.date()).days
        harvest_days = max(delta, 0)
    harvest_days_css = 'kv-amber' if (harvest_days is not None and harvest_days <= 7) else 'kv-green'

    als = (ProduceListing.query
           .filter_by(farmer_id=f.id, status='active')
           .order_by(ProduceListing.created_at.desc()).limit(5).all())
    ac  = ProduceListing.query.filter_by(farmer_id=f.id, status='active').count()
    listings_with_forecast = sum(1 for l in als if l.forecast_id)

    ral = (Notification.query.filter_by(recipient_id=f.id)
           .order_by(Notification.sent_at.desc()).limit(5).all())
    un  = Notification.query.filter_by(recipient_id=f.id, is_read=False).count()

    alerts_display = build_alerts_display(ral)

    return render_template('farmer/dashboard.html',
        farmer=f, now=now,
        farms=farms, selected_farm=sf,
        latest_reading=lr, sensor_status=ss, last_reading_ago=ago,
        quality_score=qs, quality_detail=qd, sensor_rows=sr,
        trust_score_display=ts_display, trust_score_css=ts_css,
        active_forecast=afc,
        harvest_days=harvest_days, harvest_days_css=harvest_days_css,
        active_listings=als, active_count=ac,
        listings_with_forecast=listings_with_forecast,
        alerts_display=alerts_display,
        recent_alerts=ral,
        unread_notifs=un,
        active_page='dashboard',
    )


# ══════════════════════════════════════════════════════════════
# MY FARMS
# ══════════════════════════════════════════════════════════════

@farmer_bp.route('/farms')
@login_required
@farmer_required
def farms():
    farm_list = (Farm.query
                 .filter_by(owner_id=current_user.id)
                 .order_by(Farm.created_at)
                 .all())

    farms_data = []
    for farm in farm_list:
        lr = (SensorReading.query
              .filter_by(farm_id=farm.id)
              .order_by(SensorReading.timestamp.desc())
              .first())

        listing_count = (ProduceListing.query
                         .filter_by(farm_id=farm.id,
                                    farmer_id=current_user.id,
                                    status='active')
                         .count())
        reading_count = SensorReading.query.filter_by(farm_id=farm.id).count()

        ss = sensor_status(lr) if lr else 'no-data'

        qs = farm.current_quality_score or 0
        if qs >= 70:   q_css = 'fcv-green'
        elif qs >= 40: q_css = 'fcv-amber'
        elif qs > 0:   q_css = 'fcv-danger'
        else:          q_css = ''

        last_seen = lr.timestamp.strftime('%d %b \u00b7 %H:%M') if lr else None

        farms_data.append({
            'farm':              farm,
            'sensor_status':     ss,
            'listing_count':     listing_count,
            'reading_count':     reading_count,
            'quality_score_int': qs,
            'quality_score':     str(qs) if qs else '\u2014',
            'quality_css':       q_css,
            'size_display':      f'{round(float(farm.size_hectares), 1)} ha' if farm.size_hectares else '\u2014',
            'sensor_cells':      sensor_cells(lr),
            'last_seen':         last_seen,
        })

    return render_template('farmer/farms.html',
                           active_page='farms',
                           farm_list=farm_list,
                           farms_data=farms_data,
                           farms_summary=_farms_summary(farms_data),
                           **_sidebar(current_user))


# ══════════════════════════════════════════════════════════════
# ADD FARM
# ══════════════════════════════════════════════════════════════

@farmer_bp.route('/farms/new', methods=['GET', 'POST'])
@login_required
@farmer_required
def add_farm():
    ctx = _sidebar(current_user)

    if request.method == 'POST':
        frm   = request.form
        errors = {}
        name  = frm.get('farm_name', '').strip()
        reg   = frm.get('region', '').strip()
        crop  = frm.get('crop_type', '').strip()
        town  = frm.get('town', '').strip() or None
        nid   = frm.get('sensor_node_id', '').strip().upper() or None
        notes = frm.get('notes', '').strip() or None
        sh    = _f(frm.get('size_hectares'))
        lat   = _f(frm.get('latitude'))
        lng   = _f(frm.get('longitude'))

        if not name:                       errors['farm_name']  = 'Farm name is required.'
        elif len(name) > 100:              errors['farm_name']  = 'Must be under 100 characters.'
        if not reg or reg not in _REGIONS: errors['region']     = 'Please select a valid region.'
        if not crop:                       errors['crop_type']  = 'Please select a primary crop.'
        if nid:
            clash = Farm.query.filter_by(sensor_node_id=nid).first()
            if clash and clash.owner_id != current_user.id:
                errors['sensor_node_id'] = f'{nid} is already linked to another farm.'

        if errors:
            return render_template('farmer/add_farm.html',
                                   form_errors=errors, form_data=frm,
                                   regions=_REGIONS, crops=_CROPS,
                                   initial_step=2 if 'sensor_node_id' in errors else 1,
                                   active_page='farms', **ctx)

        farm = Farm(owner_id=current_user.id, name=name, region=reg, town=town,
                    crop_type=crop, size_hectares=sh, latitude=lat, longitude=lng,
                    sensor_node_id=nid, notes=notes)
        db.session.add(farm)
        db.session.commit()
        flash(f'Farm "{name}" added successfully.', 'success')
        return redirect(url_for('farmer.farms'))

    return render_template('farmer/add_farm.html',
                           form_errors=None, form_data=None,
                           regions=_REGIONS, crops=_CROPS,
                           initial_step=1,
                           active_page='farms', **ctx)


# ══════════════════════════════════════════════════════════════
# EDIT FARM
# ══════════════════════════════════════════════════════════════

@farmer_bp.route('/farms/<int:farm_id>', methods=['GET', 'POST'])
@login_required
@farmer_required
def edit_farm(farm_id):
    farm = Farm.query.filter_by(id=farm_id, owner_id=current_user.id).first()
    if not farm:
        flash('Farm not found or access denied.', 'error')
        return redirect(url_for('farmer.farms'))

    lr  = (SensorReading.query.filter_by(farm_id=farm.id)
           .order_by(SensorReading.timestamp.desc()).first())
    ss  = sensor_status(lr)
    ctx = _sidebar(current_user)

    last_reading_preview = None
    if lr:
        vals = []
        if lr.soil_moisture  is not None: vals.append(f'Soil {round(float(lr.soil_moisture))}%')
        if lr.temperature    is not None: vals.append(f'Temp {round(float(lr.temperature), 1)}\u00b0C')
        if lr.humidity       is not None: vals.append(f'Humid {round(float(lr.humidity))}%')
        last_reading_preview = ' \u00b7 '.join(vals)

    if request.method == 'POST':
        frm   = request.form
        errors = {}
        name  = frm.get('farm_name', '').strip()
        reg   = frm.get('region', '').strip()
        crop  = frm.get('crop_type', '').strip()
        town  = frm.get('town', '').strip() or None
        nid   = frm.get('sensor_node_id', '').strip().upper() or None
        notes = frm.get('notes', '').strip() or None
        sh    = _f(frm.get('size_hectares'))
        lat   = _f(frm.get('latitude'))
        lng   = _f(frm.get('longitude'))

        if not name:                       errors['farm_name']  = 'Farm name is required.'
        if not reg or reg not in _REGIONS: errors['region']     = 'Please select a valid region.'
        if not crop:                       errors['crop_type']  = 'Please select a primary crop.'
        if nid and nid != farm.sensor_node_id:
            clash = Farm.query.filter_by(sensor_node_id=nid).first()
            if clash:
                errors['sensor_node_id'] = f'{nid} is already linked to another farm.'

        if errors:
            return render_template('farmer/edit_farm.html',
                                   farm=farm, form_errors=errors,
                                   sensor_status=ss,
                                   sensor_status_label=sensor_status_label(ss),
                                   last_reading_preview=last_reading_preview,
                                   regions=_REGIONS, crops=_CROPS,
                                   active_page='farms', **ctx)

        farm.name = name; farm.region = reg; farm.town = town
        farm.crop_type = crop; farm.size_hectares = sh
        farm.latitude = lat; farm.longitude = lng
        farm.sensor_node_id = nid; farm.notes = notes
        db.session.commit()
        flash(f'"{farm.name}" updated successfully.', 'success')
        return redirect(url_for('farmer.farms'))

    return render_template('farmer/edit_farm.html',
                           farm=farm, form_errors=None,
                           sensor_status=ss,
                           sensor_status_label=sensor_status_label(ss),
                           last_reading_preview=last_reading_preview,
                           regions=_REGIONS, crops=_CROPS,
                           active_page='farms', **ctx)


# ══════════════════════════════════════════════════════════════
# DELETE FARM
# ══════════════════════════════════════════════════════════════

@farmer_bp.route('/farms/<int:farm_id>/delete', methods=['POST'])
@login_required
@farmer_required
def delete_farm(farm_id):
    farm = Farm.query.filter_by(id=farm_id, owner_id=current_user.id).first()
    if not farm:
        flash('Farm not found.', 'error')
        return redirect(url_for('farmer.farms'))
    name = farm.name
    db.session.delete(farm)
    db.session.commit()
    flash(f'Farm "{name}" has been deleted.', 'success')
    return redirect(url_for('farmer.farms'))


# ══════════════════════════════════════════════════════════════
# MY LISTINGS
# ══════════════════════════════════════════════════════════════

@farmer_bp.route('/listings')
@login_required
@farmer_required
def listings():
    f   = current_user
    tab = request.args.get('tab', 'all')

    count_all    = ProduceListing.query.filter_by(farmer_id=f.id).count()
    count_active = ProduceListing.query.filter_by(farmer_id=f.id, status='active').count()
    count_draft  = ProduceListing.query.filter_by(farmer_id=f.id, status='draft').count()
    count_sold   = ProduceListing.query.filter_by(farmer_id=f.id, status='sold').count()

    if tab == 'active':
        raw = ProduceListing.query.filter_by(farmer_id=f.id, status='active')
    elif tab == 'draft':
        raw = ProduceListing.query.filter_by(farmer_id=f.id, status='draft')
    elif tab == 'sold':
        raw = ProduceListing.query.filter_by(farmer_id=f.id, status='sold')
    else:
        raw = ProduceListing.query.filter_by(farmer_id=f.id)

    raw_listings = raw.order_by(ProduceListing.created_at.desc()).all()

    ts = float(f.trust_score) if f.trust_score else 0.0

    farm_ids = list({l.farm_id for l in raw_listings if l.farm_id})
    farm_map  = {}
    if farm_ids:
        farm_rows = Farm.query.filter(Farm.id.in_(farm_ids)).all()
        farm_map  = {fm.id: fm.name for fm in farm_rows}

    listings_display = []
    for l in raw_listings:
        q_live = l.quality_score_live or 0
        if q_live >= 70:   q_css = 'q-good'
        elif q_live >= 40: q_css = 'q-fair'
        elif q_live > 0:   q_css = 'q-poor'
        else:              q_css = 'q-none'

        listings_display.append({
            'id':            l.id,
            'crop':          l.crop_type,
            'quantity':      f'{round(float(l.quantity_kg))} kg',
            'price':         f'XAF\u00a0{float(l.price_per_kg):,.0f}/kg',
            'status':        l.status,
            'q_live':        q_live,
            'q_css':         q_css,
            'trust':         f'{ts:.1f}',
            'has_forecast':  bool(l.forecast_id),
            'created':       l.created_at.strftime('%d %b %Y') if l.created_at else '\u2014',
            'farm_name':     farm_map.get(l.farm_id, '\u2014'),
            'photo_url':     l.photo_url or None,
            'inquiry_count': l.inquiry_count or 0,
            'description':   (l.description[:80] + '\u2026') if l.description and len(l.description) > 80 else (l.description or ''),
        })

    tab_counts = {
        'all':    count_all,
        'active': count_active,
        'draft':  count_draft,
        'sold':   count_sold,
    }

    return render_template('farmer/listings.html',
                           active_page='listings',
                           farmer=f,
                           current_tab=tab,
                           tab_counts=tab_counts,
                           listings_display=listings_display,
                           **_sidebar(f))


# ══════════════════════════════════════════════════════════════
# NEW LISTING
# ══════════════════════════════════════════════════════════════

@farmer_bp.route('/listings/new', methods=['GET', 'POST'])
@login_required
@farmer_required
def new_listing():
    f   = current_user
    ctx = _sidebar(f)

    farm_list = Farm.query.filter_by(owner_id=f.id).order_by(Farm.created_at).all()

    farm_choices = [
        {
            'id':            fm.id,
            'name':          fm.name,
            'region':        fm.region or '',
            'town':          fm.town or '',
            'crop_type':     fm.crop_type,
            'quality_score': fm.current_quality_score or 0,
            'has_sensor':    bool(fm.sensor_node_id),
        }
        for fm in farm_list
    ]

    ts = float(f.trust_score) if f.trust_score else 0.0
    ts_display = f'{ts:.1f}' if ts > 0 else '\u2014'

    if request.method == 'POST':
        frm    = request.form
        errors = {}

        farm_id = request.form.get('farm_id', type=int)
        crop    = frm.get('crop_type', '').strip()
        qty     = _f(frm.get('quantity_kg'))
        price   = _f(frm.get('price_per_kg'))
        min_ord = _f(frm.get('min_order_kg'))
        desc    = frm.get('description', '').strip() or None
        action  = frm.get('action', 'draft')

        photo_file = request.files.get('photo')

        selected_farm = Farm.query.filter_by(id=farm_id, owner_id=f.id).first() if farm_id else None

        if not selected_farm:       errors['farm_id']     = 'Please select a farm.'
        if not crop:                errors['crop_type']   = 'Please select a crop type.'
        if not qty or qty <= 0:     errors['quantity_kg'] = 'Please enter a valid quantity.'
        if not price or price <= 0: errors['price_per_kg']= 'Please enter a valid price.'

        if errors:
            return render_template('farmer/listing_new.html',
                                   active_page='listings',
                                   farm_choices=farm_choices, crops=_CROPS,
                                   form_errors=errors, form_data=frm,
                                   ts_display=ts_display,
                                   preselect_farm_id=farm_id,
                                   **ctx)

        photo_url = _save_photo(photo_file)

        status = 'active' if action == 'publish' else 'draft'
        quality_at_listing = selected_farm.current_quality_score or 0

        listing = ProduceListing(
            farmer_id=f.id,
            farm_id=selected_farm.id,
            crop_type=crop,
            quantity_kg=qty,
            price_per_kg=price,
            min_order_kg=min_ord,
            description=desc,
            photo_url=photo_url,
            quality_score_at_listing=quality_at_listing,
            quality_score_live=quality_at_listing,
            status=status,
        )
        db.session.add(listing)
        db.session.commit()

        verb = 'published' if status == 'active' else 'saved as draft'
        flash(f'Listing "{crop}" {verb} successfully.', 'success')
        return redirect(url_for('farmer.listings'))

    preselect_farm_id = request.args.get('farm_id', type=int)

    return render_template('farmer/listing_new.html',
                           active_page='listings',
                           farm_choices=farm_choices, crops=_CROPS,
                           form_errors=None, form_data=None,
                           ts_display=ts_display,
                           preselect_farm_id=preselect_farm_id,
                           **ctx)


# ══════════════════════════════════════════════════════════════
# EDIT LISTING
# ══════════════════════════════════════════════════════════════

@farmer_bp.route('/listings/<int:lid>', methods=['GET', 'POST'])
@login_required
@farmer_required
def edit_listing(lid):
    f       = current_user
    listing = ProduceListing.query.filter_by(id=lid, farmer_id=f.id).first()
    if not listing:
        flash('Listing not found or access denied.', 'error')
        return redirect(url_for('farmer.listings'))

    ctx = _sidebar(f)

    current_farm = Farm.query.get(listing.farm_id) if listing.farm_id else None

    farm_list = Farm.query.filter_by(owner_id=f.id).order_by(Farm.created_at).all()
    farm_choices = [
        {
            'id':            fm.id,
            'name':          fm.name,
            'region':        fm.region or '',
            'crop_type':     fm.crop_type,
            'quality_score': fm.current_quality_score or 0,
        }
        for fm in farm_list
    ]

    ts = float(f.trust_score) if f.trust_score else 0.0
    ts_display = f'{ts:.1f}' if ts > 0 else '\u2014'
    is_live = listing.status == 'active'

    if request.method == 'POST':
        frm    = request.form
        action = frm.get('action', 'save')

        if action == 'delist':
            listing.status = 'delisted'
            db.session.commit()
            flash(f'"{listing.crop_type}" listing has been delisted.', 'success')
            return redirect(url_for('farmer.listings'))

        errors = {}
        crop    = frm.get('crop_type', '').strip()
        qty     = _f(frm.get('quantity_kg'))
        price   = _f(frm.get('price_per_kg'))
        min_ord = _f(frm.get('min_order_kg'))
        desc    = frm.get('description', '').strip() or None

        if not crop:                errors['crop_type']   = 'Please select a crop type.'
        if not qty or qty <= 0:     errors['quantity_kg'] = 'Please enter a valid quantity.'
        if not price or price <= 0: errors['price_per_kg']= 'Please enter a valid price.'

        if errors:
            return render_template('farmer/listing_edit.html',
                                   active_page='listings',
                                   listing=listing, farm_choices=farm_choices,
                                   crops=_CROPS, form_errors=errors,
                                   ts_display=ts_display, is_live=is_live,
                                   current_farm=current_farm,
                                   **ctx)

        listing.crop_type    = crop
        listing.quantity_kg  = qty
        listing.price_per_kg = price
        listing.min_order_kg = min_ord
        listing.description  = desc
        if action == 'publish':
            listing.status = 'active'
        db.session.commit()
        flash(f'"{listing.crop_type}" updated successfully.', 'success')
        return redirect(url_for('farmer.listings'))

    return render_template('farmer/listing_edit.html',
                           active_page='listings',
                           listing=listing, farm_choices=farm_choices,
                           crops=_CROPS, form_errors=None,
                           ts_display=ts_display, is_live=is_live,
                           current_farm=current_farm,
                           **ctx)


# ══════════════════════════════════════════════════════════════
# FORECASTS INDEX
# ══════════════════════════════════════════════════════════════

@farmer_bp.route('/forecasts')
@login_required
@farmer_required
def forecasts():
    f = current_user
    active = (HarvestForecast.query
              .join(Farm, Farm.id == HarvestForecast.farm_id)
              .filter(Farm.owner_id == f.id, HarvestForecast.is_active == True)
              .order_by(HarvestForecast.created_at.desc())
              .first())
    if active:
        return redirect(url_for('farmer.forecast_detail', forecast_id=active.id))

    farms = Farm.query.filter_by(owner_id=f.id).all()
    total_readings = sum(
        SensorReading.query.filter_by(farm_id=farm.id).count()
        for farm in farms
    )
    readings_needed = 1344  # 28 days x 48 readings/day
    progress_pct = min(round(total_readings / readings_needed * 100), 99) if total_readings else 0

    return render_template('farmer/forecasts_empty.html',
                           farms=farms,
                           total_readings=total_readings,
                           readings_needed=readings_needed,
                           progress_pct=progress_pct,
                           active_page='forecasts',
                           **_sidebar(f))


# ══════════════════════════════════════════════════════════════
# FORECAST DETAIL
# ══════════════════════════════════════════════════════════════

@farmer_bp.route('/forecasts/<int:forecast_id>')
@login_required
@farmer_required
def forecast_detail(forecast_id):
    f = current_user

    forecast = HarvestForecast.query.filter(
        HarvestForecast.id == forecast_id,
        HarvestForecast.farm_id == Farm.id,
        Farm.owner_id == f.id
    ).first()

    if not forecast:
        flash('Forecast not found or access denied.', 'error')
        return redirect(url_for('farmer.dashboard'))

    ctx = compute_forecast_context(forecast, f)

    return render_template('farmer/forecast_detail.html',
        farmer=f,
        forecast=forecast,
        active_page='forecasts',
        **ctx,
        **_sidebar(f),
    )


# ══════════════════════════════════════════════════════════════
# TRUST SCORE
# ══════════════════════════════════════════════════════════════

@farmer_bp.route('/trust')
@login_required
@farmer_required
def trust_score():
    ctx = compute_trust_context(current_user)

    return render_template('farmer/trust_score.html',
        farmer=current_user,
        active_page='trust',
        **ctx,
        **_sidebar(current_user),
    )


# ══════════════════════════════════════════════════════════════
# NOTIFICATIONS & PROFILE (stubs)
# ══════════════════════════════════════════════════════════════

@farmer_bp.route('/notifications', methods=['GET', 'POST'])
@login_required
@farmer_required
def notifications():
    tab = request.args.get('tab', 'all')

    # ── POST — mark read / mark all read ─────────────────────
    if request.method == 'POST':
        action = request.form.get('action', '')
        if action == 'mark_all_read':
            Notification.query.filter_by(
                recipient_id=current_user.id, is_read=False
            ).update({'is_read': True})
            db.session.commit()
            flash('All notifications marked as read.', 'success')
        elif action == 'mark_read':
            nid = request.form.get('notif_id', type=int)
            if nid:
                n = Notification.query.filter_by(
                    id=nid, recipient_id=current_user.id).first()
                if n:
                    n.is_read = True
                    db.session.commit()
        elif action == 'delete':
            nid = request.form.get('notif_id', type=int)
            if nid:
                n = Notification.query.filter_by(
                    id=nid, recipient_id=current_user.id).first()
                if n:
                    db.session.delete(n)
                    db.session.commit()
        return redirect(url_for('farmer.notifications') + f'?tab={tab}')

    # ── GET — fetch all notifications ────────────────────────
    all_notifs = (Notification.query
                  .filter_by(recipient_id=current_user.id)
                  .order_by(Notification.sent_at.desc())
                  .all())

    # ── Tab filter mapping ────────────────────────────────────
    FARM_TYPES   = {'harvest_alert', 'sensor_offline', 'quality_change'}
    BUYER_TYPES  = {'buyer_enquiry'}
    SYSTEM_TYPES = {'account_verified', 'account_suspended', 'listing_published',
                    'transaction_completed', 'system'}

    if tab == 'unread':
        filtered = [n for n in all_notifs if not n.is_read]
    elif tab == 'farm':
        filtered = [n for n in all_notifs if n.type in FARM_TYPES]
    elif tab == 'buyer':
        filtered = [n for n in all_notifs if n.type in BUYER_TYPES]
    elif tab == 'system':
        filtered = [n for n in all_notifs if n.type in SYSTEM_TYPES]
    else:
        filtered = all_notifs

    # ── Notification type label + colour mapping ──────────────
    TYPE_META = {
        'harvest_alert'       : ('amber', 'Harvest forecast'),
        'sensor_offline'      : ('gray',  'Sensor offline'),
        'quality_change'      : ('teal',  'Quality update'),
        'buyer_enquiry'       : ('blue',  'Buyer enquiry'),
        'listing_published'   : ('green', 'Listing published'),
        'transaction_completed': ('green','Transaction complete'),
        'account_verified'    : ('teal',  'Account verified'),
        'account_suspended'   : ('red',   'Account suspended'),
        'system'              : ('gray',  'System'),
    }

    # ── Build display list ────────────────────────────────────
    notifications_display = []
    for n in filtered:
        colour, type_label = TYPE_META.get(n.type, ('gray', 'Notification'))

        # Compute human-readable time
        secs = (datetime.utcnow() - n.sent_at).total_seconds() if n.sent_at else 0
        if secs < 60:       t = 'Just now'
        elif secs < 3600:   m = int(secs // 60);  t = f'{m} minute{"s" if m != 1 else ""} ago'
        elif secs < 86400:  h = int(secs // 3600); t = f'{h} hour{"s" if h != 1 else ""} ago'
        elif secs < 172800: t = f'Yesterday, {n.sent_at.strftime("%H:%M")}'
        elif secs < 604800: t = f'{int(secs // 86400)} days ago'
        else:               t = n.sent_at.strftime('%b %d, %Y')

        # Action URL
        action_url   = None
        action_label = 'View'
        if n.type == 'buyer_enquiry':
            action_url   = url_for('farmer.enquiries')
            action_label = 'View enquiries'
        elif n.forecast_id:
            action_url   = url_for('farmer.forecast_detail', forecast_id=n.forecast_id)
            action_label = 'View forecast'
        elif n.listing_id:
            action_url   = url_for('farmer.edit_listing', lid=n.listing_id)
            action_label = 'View listing'
        elif n.type == 'sensor_offline':
            action_url   = url_for('farmer.farms')
            action_label = 'View farm'

        notifications_display.append({
            'id'          : n.id,
            'type'        : n.type,
            'type_label'  : type_label,
            'colour'      : colour,
            'title'       : n.title,
            'message'     : n.message,
            'time_display': t,
            'sent_at'     : n.sent_at,
            'action_url'  : action_url,
            'action_label': action_label,
            'is_unread'   : not n.is_read,
        })

    # ── Tab counts ────────────────────────────────────────────
    tab_counts = {
        'all':    len(all_notifs),
        'unread': sum(1 for n in all_notifs if not n.is_read),
        'farm':   sum(1 for n in all_notifs if n.type in FARM_TYPES),
        'buyer':  sum(1 for n in all_notifs if n.type in BUYER_TYPES),
        'system': sum(1 for n in all_notifs if n.type in SYSTEM_TYPES),
    }

    return render_template('farmer/notifications.html',
        notifications_display = notifications_display,
        active_tab            = tab,
        tab_counts            = tab_counts,
        active_page           = 'notifications',
        **_sidebar(current_user),
    )


# ══════════════════════════════════════════════════════════════
# FARMER PROFILE — OWN VIEW (WF16)
# Private. Only the logged-in farmer sees this.
# Handles: GET (tab display) + POST (update_photo, update_info,
#          change_password, update_notifs, delete_account)
# ══════════════════════════════════════════════════════════════

@farmer_bp.route('/profile', methods=['GET', 'POST'])
@login_required
@farmer_required
def profile():
    f   = current_user
    ctx = _sidebar(f)
    tab = request.args.get('tab', 'info')

    # ── Build farms_data ──────────────────────────────────────
    farm_list = Farm.query.filter_by(owner_id=f.id).order_by(Farm.created_at).all()
    farms_data = []
    for farm in farm_list:
        lr = (SensorReading.query.filter_by(farm_id=farm.id)
              .order_by(SensorReading.timestamp.desc()).first())
        ss = sensor_status(lr) if lr else 'no-data'
        qs = farm.current_quality_score or 0
        if qs >= 70:   q_css = 'fcv-green'
        elif qs >= 40: q_css = 'fcv-amber'
        elif qs > 0:   q_css = 'fcv-danger'
        else:          q_css = ''
        farms_data.append({
            'farm':          farm,
            'sensor_status': ss,
            'quality_score': str(qs) if qs else '—',
            'quality_css':   q_css,
            'size_display':  f'{round(float(farm.size_hectares), 1)} ha' if farm.size_hectares else '—',
        })

    # ── Build listings_display ────────────────────────────────
    raw_listings = (ProduceListing.query.filter_by(farmer_id=f.id)
                    .order_by(ProduceListing.created_at.desc()).all())
    farm_ids = list({l.farm_id for l in raw_listings if l.farm_id})
    farm_map = {}
    if farm_ids:
        farm_rows = Farm.query.filter(Farm.id.in_(farm_ids)).all()
        farm_map  = {fm.id: fm.name for fm in farm_rows}
    listings_display = [{
        'id':        l.id,
        'crop':      l.crop_type,
        'quantity':  f'{round(float(l.quantity_kg))} kg',
        'price':     f'XAF\u00a0{float(l.price_per_kg):,.0f}/kg',
        'status':    l.status,
        'q_live':    l.quality_score_live or 0,
        'farm_name': farm_map.get(l.farm_id, '—'),
    } for l in raw_listings]

    # ── Build earnings ────────────────────────────────────────
    now         = datetime.utcnow()
    month_start = datetime(now.year, now.month, 1)
    completed_txns = (Transaction.query
                      .filter_by(farmer_id=f.id, status='completed')
                      .order_by(Transaction.completed_at.desc()).all())
    total_earned = sum(float(t.total_amount) for t in completed_txns if t.total_amount)
    this_month   = sum(
        float(t.total_amount) for t in completed_txns
        if t.total_amount and t.completed_at and t.completed_at >= month_start
    )
    recent_txns = []
    for t in completed_txns[:5]:
        listing = ProduceListing.query.get(t.listing_id) if t.listing_id else None
        recent_txns.append({
            'crop':           listing.crop_type if listing else '—',
            'quantity_kg':    round(float(t.quantity_kg)) if t.quantity_kg else '—',
            'buyer_initials': f'B-{t.buyer_id}',
            'date':           t.completed_at.strftime('%d %b %Y') if t.completed_at else '—',
            'amount':         float(t.total_amount) if t.total_amount else 0,
            'amount_css':     '',
            'is_late':        t.is_on_time is False,
        })
    earnings = {
        'total_transactions':  len(completed_txns),
        'total_earned':        total_earned,
        'this_month':          this_month,
        'recent_transactions': recent_txns,
    }

    # ── Build trust_ctx ───────────────────────────────────────
    ts              = float(f.trust_score) if f.trust_score else 0.0
    total_txn_count = len(completed_txns)
    on_time_count   = sum(1 for t in completed_txns if t.is_on_time is True)
    completion_pct  = round(len(completed_txns) / max(1, total_txn_count) * 100)
    delivery_pct    = round(on_time_count / max(1, total_txn_count) * 100)

    all_ratings = Rating.query.filter_by(farmer_id=f.id).all()
    avg_rating  = (sum(r.score for r in all_ratings) / len(all_ratings)) if all_ratings else 0
    rating_pct  = round(avg_rating / 5 * 100) if avg_rating else 0

    profile_pct = 100 if (f.full_name and f.email and f.phone and f.region and f.primary_crop) else (
        80 if (f.full_name and f.email and f.region) else 50
    )

    trust_ctx = {
        'score_display':     f'{ts:.1f}' if ts > 0 else None,
        'transaction_count': total_txn_count,
        'bar_rows': [
            {'label': 'Transaction completion', 'pct': completion_pct,
             'display': f'{completion_pct}% × 40%'},
            {'label': 'On-time delivery',       'pct': delivery_pct,
             'display': f'{delivery_pct}% × 30%'},
            {'label': 'Buyer ratings (1–5 ★)',  'pct': rating_pct,
             'display': f'{avg_rating:.1f}/5 × 20%'},
            {'label': 'Profile completeness',   'pct': profile_pct,
             'display': f'{profile_pct}% × 10%'},
        ],
    }

    # ── POST handlers ─────────────────────────────────────────
    if request.method == 'POST':
        action = request.form.get('action', '')

        # ── update_photo ───────────────────────────────────────
        # Triggered when the farmer clicks the camera icon and
        # selects an image. The form auto-submits via onchange.
        if action == 'update_photo':
            photo_file = request.files.get('profile_photo')

            if not photo_file or not photo_file.filename:
                flash('No file selected. Please choose an image.', 'error')
                return redirect(url_for('farmer.profile') + '?tab=info')

            allowed = {'jpg', 'jpeg', 'png', 'webp'}
            ext = photo_file.filename.rsplit('.', 1)[-1].lower() if '.' in photo_file.filename else ''
            if ext not in allowed:
                flash('Only JPG, PNG, or WEBP images are allowed.', 'error')
                return redirect(url_for('farmer.profile') + '?tab=info')

            # Save new photo to static/uploads/
            photo_url = _save_photo(photo_file)
            if not photo_url:
                flash('Could not save the image. Please try again.', 'error')
                return redirect(url_for('farmer.profile') + '?tab=info')

            # Delete the old photo file from disk to save space
            if f.profile_photo_url:
                old_path = os.path.join(
                    current_app.config.get(
                        'UPLOAD_FOLDER',
                        os.path.join(current_app.root_path, 'static', 'uploads')
                    ),
                    os.path.basename(f.profile_photo_url)
                )
                if os.path.exists(old_path):
                    os.remove(old_path)

            f.profile_photo_url = photo_url
            db.session.commit()
            flash('Profile photo updated successfully.', 'success')
            return redirect(url_for('farmer.profile') + '?tab=info')

        # ── update_info ────────────────────────────────────────
        elif action == 'update_info':
            errors = {}
            first  = request.form.get('first_name', '').strip()
            last   = request.form.get('last_name',  '').strip()
            email  = request.form.get('email',      '').strip()
            phone  = request.form.get('phone',      '').strip() or None
            region = request.form.get('region',     '').strip()
            crop   = request.form.get('primary_crop', '').strip()

            if not first: errors['first_name'] = 'First name is required.'
            if not last:  errors['last_name']  = 'Last name is required.'
            if not email: errors['email']      = 'Email address is required.'
            elif email != f.email:
                from models.models import User as UserModel
                clash = UserModel.query.filter_by(email=email).first()
                if clash and clash.id != f.id:
                    errors['email'] = 'That email is already in use.'

            if errors:
                return render_template('farmer/profile.html',
                    farmer=f, farms_data=farms_data,
                    listings_display=listings_display, earnings=earnings,
                    trust_ctx=trust_ctx, regions=_REGIONS, crops=_CROPS,
                    form_errors=errors, form_data=request.form,
                    active_tab='info', active_page='profile', **ctx)

            f.full_name    = f'{first} {last}'
            f.email        = email
            f.phone        = phone
            f.region       = region if region in _REGIONS else f.region
            f.primary_crop = crop
            db.session.commit()
            flash('Profile updated successfully.', 'success')
            return redirect(url_for('farmer.profile') + '?tab=info')

        # ── change_password ────────────────────────────────────
        elif action == 'change_password':
            errors  = {}
            cur_pw  = request.form.get('current_password', '')
            new_pw  = request.form.get('new_password',     '')
            conf_pw = request.form.get('confirm_password', '')

            if not check_password_hash(f.password_hash, cur_pw):
                errors['current_password'] = 'Current password is incorrect.'
            if len(new_pw) < 8:
                errors['new_password'] = 'New password must be at least 8 characters.'
            if new_pw != conf_pw:
                errors['confirm_password'] = 'Passwords do not match.'

            if errors:
                return render_template('farmer/profile.html',
                    farmer=f, farms_data=farms_data,
                    listings_display=listings_display, earnings=earnings,
                    trust_ctx=trust_ctx, regions=_REGIONS, crops=_CROPS,
                    form_errors=errors, form_data=request.form,
                    active_tab='settings', active_page='profile', **ctx)

            f.password_hash = generate_password_hash(new_pw)
            db.session.commit()
            flash('Password updated successfully.', 'success')
            return redirect(url_for('farmer.profile') + '?tab=settings')

        # ── update_notifs (stub — stores nothing yet) ──────────
        elif action == 'update_notifs':
            flash('Notification preferences saved.', 'success')
            return redirect(url_for('farmer.profile') + '?tab=settings')

        # ── delete_account ─────────────────────────────────────
        elif action == 'delete_account':
            db.session.delete(f)
            db.session.commit()
            logout_user()
            flash('Your account has been permanently deleted.', 'success')
            return redirect(url_for('public.landing'))

    return render_template('farmer/profile.html',
        farmer=f,
        farms_data=farms_data,
        listings_display=listings_display,
        earnings=earnings,
        trust_ctx=trust_ctx,
        regions=_REGIONS,
        crops=_CROPS,
        form_errors=None,
        form_data=None,
        active_tab=tab,
        active_page='profile',
        **ctx,
    )
 
 
# ══════════════════════════════════════════════════════════════
# FARMER PROFILE — REGISTERED VIEW (WF17)
# Logged-in user viewing another farmer's profile.
# Shows trust breakdown + farm names + active listings.
# Hides: contact details, drafts, earnings, sensor data.
# ══════════════════════════════════════════════════════════════
 
@farmer_bp.route('/<int:farmer_id>/profile')
@login_required
def farmer_profile_registered(farmer_id):
    from models.models import User as UserModel, Transaction as Txn, Rating as Rat
    subject = UserModel.query.filter_by(id=farmer_id, role='farmer').first()
    if not subject:
        flash('Farmer not found.', 'error')
        return redirect(url_for('buyer.marketplace'))
 
    # Redirect farmer viewing their own profile
    if current_user.id == farmer_id:
        return redirect(url_for('farmer.profile'))
 
    farm_list = Farm.query.filter_by(owner_id=farmer_id).order_by(Farm.created_at).all()
    farms_data = [{
        'farm':         farm,
        'size_display': f'{round(float(farm.size_hectares), 1)} ha' if farm.size_hectares else None,
    } for farm in farm_list]
 
    raw_listings = (ProduceListing.query
                    .filter_by(farmer_id=farmer_id, status='active')
                    .order_by(ProduceListing.created_at.desc()).all())
    ts_val = float(subject.trust_score) if subject.trust_score else 0.0
    active_listings = [{
        'id':           l.id,
        'crop':         l.crop_type,
        'quantity':     f'{round(float(l.quantity_kg))} kg',
        'price':        f'XAF\u00a0{float(l.price_per_kg):,.0f}/kg',
        'q_live':       l.quality_score_live or 0,
        'has_forecast': bool(l.forecast_id),
    } for l in raw_listings]
 
    # Trust context
    completed_txns = Txn.query.filter_by(farmer_id=farmer_id, status='completed').all()
    on_time  = sum(1 for t in completed_txns if t.is_on_time is True)
    comp_pct = round(len(completed_txns) / max(1, len(completed_txns)) * 100) if completed_txns else 0
    del_pct  = round(on_time / max(1, len(completed_txns)) * 100) if completed_txns else 0
    all_r    = Rat.query.filter_by(farmer_id=farmer_id).all()
    avg_r    = (sum(r.score for r in all_r) / len(all_r)) if all_r else 0
    rat_pct  = round(avg_r / 5 * 100)
    prof_pct = 100 if (subject.full_name and subject.email and subject.phone
                       and subject.region and subject.primary_crop) else 70
 
    trust_ctx = {
        'score_display':     f'{ts_val:.1f}' if ts_val > 0 else None,
        'transaction_count': len(completed_txns),
        'bar_rows': [
            {'label': 'Transaction completion', 'pct': comp_pct, 'display': f'{comp_pct}%'},
            {'label': 'On-time delivery',       'pct': del_pct,  'display': f'{del_pct}%'},
            {'label': 'Buyer ratings (1–5 ★)',  'pct': rat_pct,  'display': f'{avg_r:.1f} / 5'},
            {'label': 'Profile completeness',   'pct': prof_pct, 'display': f'{prof_pct}%'},
        ],
    }
 
    un = Notification.query.filter_by(recipient_id=current_user.id, is_read=False).count()
    active_fc = (HarvestForecast.query
                 .join(Farm, Farm.id == HarvestForecast.farm_id)
                 .filter(Farm.owner_id == current_user.id, HarvestForecast.is_active == True)
                 .order_by(HarvestForecast.created_at.desc()).first()
                 if current_user.role == 'farmer' else None)
 
    return render_template('farmer/profile_registered.html',
        subject_farmer=subject,
        farms_data=farms_data,
        active_listings=active_listings,
        trust_ctx=trust_ctx,
        active_page='',
        unread_notifs=un,
        active_forecast=active_fc,
    )


# ══════════════════════════════════════════════════════════════
# FARMER ENQUIRIES INBOX  —  GET/POST /farmer/enquiries
#
# Shows all messages received by this farmer.
# POST with action='reply'  — saves reply, notifies sender.
# POST with action='mark_read' — marks a message as read.
#
# OOP NOTE:
#   Uses ContactRequest.can_reply(user) and
#   ContactRequest.is_unread_for(user) — the object decides
#   its own state. The route just orchestrates.
# ══════════════════════════════════════════════════════════════
@farmer_bp.route('/enquiries', methods=['GET', 'POST'])
@login_required
@farmer_required
def enquiries():
    sb = _sidebar(current_user)

    # ── POST — handle reply or mark-as-read ───────────────────
    if request.method == 'POST':
        action      = request.form.get('action', '')
        enquiry_id  = request.form.get('enquiry_id', type=int)

        enquiry = ContactRequest.query.get(enquiry_id) if enquiry_id else None

        # Safety: only the recipient can act on their own messages
        if not enquiry or enquiry.recipient_id != current_user.id:
            flash('Message not found.', 'error')
            return redirect(url_for('farmer.enquiries'))

        # ── Reply ─────────────────────────────────────────────
        if action == 'reply':
            if not enquiry.can_reply(current_user):
                flash('You have already replied to this message.', 'error')
                return redirect(url_for('farmer.enquiries'))

            reply_text = request.form.get('reply_message', '').strip()

            if not reply_text:
                flash('Your reply cannot be empty.', 'error')
                return redirect(url_for('farmer.enquiries'))

            if len(reply_text) > 1000:
                flash('Reply is too long. Please keep it under 1000 characters.', 'error')
                return redirect(url_for('farmer.enquiries'))

            # Save the reply on the ContactRequest object
            enquiry.reply_message = reply_text
            enquiry.replied_at    = datetime.utcnow()
            enquiry.status        = 'replied'

            # Notify the original sender that a reply has arrived
            notification = Notification(
                recipient_id = enquiry.sender_id,
                type         = 'buyer_enquiry',
                title        = 'Your enquiry has been replied to',
                message      = (
                    f'{current_user.full_name} replied to your message: '
                    f'"{reply_text[:80]}{"…" if len(reply_text) > 80 else ""}"'
                ),
                is_read = False,
                sent_at = datetime.utcnow(),
            )
            db.session.add(notification)
            db.session.commit()

            flash('Your reply has been sent.', 'success')
            return redirect(url_for('farmer.enquiries'))

        # ── Mark as read ──────────────────────────────────────
        elif action == 'mark_read':
            if enquiry.status == 'sent':
                enquiry.status  = 'read'
                enquiry.read_at = datetime.utcnow()
                db.session.commit()
            return redirect(url_for('farmer.enquiries'))

    # ── GET — build inbox display ─────────────────────────────
    tab = request.args.get('tab', 'all')   # all | listing | profile | farmer

    # Fetch all messages addressed to this farmer, newest first
    all_enquiries = (
        ContactRequest.query
        .filter_by(recipient_id=current_user.id)
        .order_by(ContactRequest.created_at.desc())
        .all()
    )

    # Mark any 'sent' messages as 'read' now that the farmer
    # is looking at them (auto-read on open)
    changed = False
    for eq in all_enquiries:
        if eq.status == 'sent':
            eq.status  = 'read'
            eq.read_at = datetime.utcnow()
            changed = True
    if changed:
        db.session.commit()

    # Build display dicts — template receives clean data, not ORM objects
    def _build_display(eq):
        sender = User.query.get(eq.sender_id)
        listing_label = None
        if eq.listing_id:
            from models.models import ProduceListing
            pl = ProduceListing.query.get(eq.listing_id)
            listing_label = pl.crop_type if pl else 'Deleted listing'

        return {
            'id':             eq.id,
            'sender_name':    sender.full_name if sender else 'Unknown user',
            'sender_role':    sender.role      if sender else 'unknown',
            'sender_id':      eq.sender_id,
            'context_type':   eq.context_type,
            'context_label':  eq.context_label,       # uses @property on model
            'listing_label':  listing_label,
            'message':        eq.message,
            'reply_message':  eq.reply_message,
            'status':         eq.status,
            'created_ago':    _ago(eq.created_at),
            'replied_ago':    _ago(eq.replied_at) if eq.replied_at else None,
            'can_reply':      eq.can_reply(current_user),
        }

    display_list = [_build_display(eq) for eq in all_enquiries]

    # Tab filtering
    if tab == 'listing':
        filtered = [e for e in display_list if e['context_type'] == 'listing_enquiry']
    elif tab == 'profile':
        filtered = [e for e in display_list if e['context_type'] == 'farmer_profile']
    elif tab == 'farmer':
        filtered = [e for e in display_list if e['context_type'] == 'farmer_to_farmer']
    else:
        filtered = display_list

    # Tab counts for the tab bar badges
    counts = {
        'all':     len(display_list),
        'listing': sum(1 for e in display_list if e['context_type'] == 'listing_enquiry'),
        'profile': sum(1 for e in display_list if e['context_type'] == 'farmer_profile'),
        'farmer':  sum(1 for e in display_list if e['context_type'] == 'farmer_to_farmer'),
    }

    # Unread count for the sidebar badge (recalculate after auto-read)
    sb = _sidebar(current_user)

    return render_template(
        'farmer/enquiries.html',
        enquiries    = filtered,
        counts       = counts,
        active_tab   = tab,
        active_page  = 'enquiries',
        **sb,
    )



#
# Handles a farmer sending a message to another farmer.
# Called from profile_registered.html — the page a farmer
# sees when viewing another farmer's profile.
#
# OOP NOTE:
#   Same pattern as buyer contact_send. One responsibility:
#   receive, validate, save, notify. The ContactRequest object
#   handles what it knows about itself. This route directs traffic.
# ══════════════════════════════════════════════════════════════
@farmer_bp.route('/contact/send', methods=['POST'])
@login_required
@farmer_required
def farmer_contact_send():
    """
    Farmer sends a message to another farmer.

    Form fields expected:
      recipient_id  — user.id of the farmer being contacted
      message       — the message text
      redirect_back — URL to return to after submission

    context_type is always 'farmer_to_farmer' for this route.
    """
    # ── Read form fields ──────────────────────────────────────
    recipient_id  = request.form.get('recipient_id',  type=int)
    message_text  = request.form.get('message',       '').strip()
    redirect_back = request.form.get('redirect_back', '')

    # ── Validate ──────────────────────────────────────────────
    if not recipient_id:
        flash('Could not identify the recipient. Please try again.', 'error')
        return redirect(redirect_back or url_for('farmer.dashboard'))

    if not message_text:
        flash('Your message cannot be empty.', 'error')
        return redirect(redirect_back or url_for('farmer.dashboard'))

    if len(message_text) > 1000:
        flash('Message is too long. Please keep it under 1000 characters.', 'error')
        return redirect(redirect_back or url_for('farmer.dashboard'))

    # ── Check recipient exists and is a farmer ────────────────
    recipient = User.query.get(recipient_id)
    if not recipient or recipient.role != 'farmer':
        flash('Farmer not found.', 'error')
        return redirect(redirect_back or url_for('farmer.dashboard'))

    # ── Guard: cannot message yourself ───────────────────────
    if recipient_id == current_user.id:
        flash('You cannot send a message to yourself.', 'error')
        return redirect(redirect_back or url_for('farmer.dashboard'))

    # ── Create the ContactRequest object ──────────────────────
    enquiry = ContactRequest(
        sender_id    = current_user.id,
        recipient_id = recipient_id,
        context_type = 'farmer_to_farmer',
        listing_id   = None,
        message      = message_text,
        status       = 'sent',
        created_at   = datetime.utcnow(),
    )
    db.session.add(enquiry)

    # ── Notify the recipient farmer ───────────────────────────
    notification = Notification(
        recipient_id = recipient_id,
        type         = 'buyer_enquiry',
        title        = 'New farmer message',
        message      = (
            f'Fellow farmer {current_user.full_name} '
            f'sent you a message.'
        ),
        is_read  = False,
        sent_at  = datetime.utcnow(),
    )
    db.session.add(notification)

    db.session.commit()

    flash(
        f'Your message has been sent to {recipient.full_name}.',
        'success'
    )

    if redirect_back:
        return redirect(redirect_back)
    return redirect(url_for('farmer.dashboard'))
