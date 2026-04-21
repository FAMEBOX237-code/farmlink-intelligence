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
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from extensions  import db
from models.models import (
    Farm, SensorReading, HarvestForecast,
    ProduceListing, Notification
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
    """Unread count + active forecast for sidebar badge."""
    unread = Notification.query.filter_by(recipient_id=u.id, is_read=False).count()
    fc = (HarvestForecast.query
          .join(Farm, Farm.id == HarvestForecast.farm_id)
          .filter(Farm.owner_id == u.id, HarvestForecast.is_active == True)
          .order_by(HarvestForecast.created_at.desc())
          .first())
    return dict(unread_notifs=unread, active_forecast=fc)


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

@farmer_bp.route('/notifications')
@login_required
@farmer_required
def notifications():
    return render_template('farmer/notifications.html',
                           active_page='notifications', **_sidebar(current_user))


@farmer_bp.route('/profile', methods=['GET', 'POST'])
@login_required
@farmer_required
def profile():
    return render_template('farmer/profile.html',
                           active_page='profile', **_sidebar(current_user))