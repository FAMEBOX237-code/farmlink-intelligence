# ============================================================
# routes/farmer.py — FarmLink Intelligence  (Sprint 3)
# Refactored: SQLAlchemy ORM → raw SQL via db.session.execute()
# ============================================================

from functools import wraps
from datetime import datetime, date
from collections import defaultdict

from flask import (Blueprint, render_template, redirect, url_for,
                   request, flash, jsonify)
from flask_login import login_required, current_user
from sqlalchemy import text

from extensions import db

farmer_bp = Blueprint('farmer', __name__, url_prefix='/farmer')

_REGIONS = ['Centre','West','Littoral','North West','South West',
            'Adamawa','North','Far North','East','South']

_CROPS = ['Tomatoes','Maize','Plantains','Cassava','Yams','Sweet potatoes',
          'Groundnuts','Beans','Pepper','Cocoa','Coffee','Palm oil','Mixed crops','Other']


# ── Guards & helpers ──────────────────────────────────────────

def farmer_required(f):
    @wraps(f)
    def d(*a, **kw):
        if not current_user.is_authenticated or current_user.role != 'farmer':
            return redirect(url_for('public.forbidden_direct'))
        return f(*a, **kw)
    return d


def _ago(dt):
    if not dt: return 'never'
    s = (datetime.utcnow() - dt).total_seconds()
    if s < 60:     return 'just now'
    if s < 3600:   m=int(s//60);   return f'{m} minute{"s"if m!=1 else""} ago'
    if s < 86400:  h=int(s//3600); return f'{h} hour{"s"if h!=1 else""} ago'
    if s < 172800: return 'yesterday'
    return f'{int(s//86400)} days ago'


def _status(r):
    if not r: return 'offline'
    m = (datetime.utcnow() - r.timestamp).total_seconds() / 60
    return 'online' if m <= 35 else ('warning' if m <= 65 else 'offline')


def _qdetail(r):
    if not r: return {}
    d = {}
    sm  = float(r.soil_moisture)   if r.soil_moisture   is not None else None
    tmp = float(r.temperature)     if r.temperature     is not None else None
    hum = float(r.humidity)        if r.humidity        is not None else None
    lux = float(r.light_intensity) if r.light_intensity is not None else None
    if sm  is not None: d['Soil moisture'] = 'Good' if 40<=sm<=80    else ('Fair' if sm>=25      else 'Poor')
    if tmp is not None: d['Temperature']   = 'Good' if 18<=tmp<=32   else ('Fair' if 12<=tmp<=38 else 'Poor')
    if hum is not None: d['Humidity']      = 'Good' if 50<=hum<=85   else ('Fair' if hum>=35     else 'Poor')
    if lux is not None: d['Light']         = 'Good' if 2000<=lux<=8000 else ('Fair' if 500<=lux<=12000 else 'Poor')
    return d


def _sidebar(u):
    unread = db.session.execute(
        text("SELECT COUNT(*) FROM notifications WHERE recipient_id = :uid AND is_read = 0"),
        {'uid': u.id}
    ).scalar()
    fc = db.session.execute(
        text("""
            SELECT hf.*
            FROM harvest_forecasts hf
            JOIN farms f ON f.id = hf.farm_id
            WHERE f.owner_id = :uid AND hf.is_active = 1
            ORDER BY hf.created_at DESC
            LIMIT 1
        """),
        {'uid': u.id}
    ).fetchone()
    return dict(unread_notifs=unread, active_forecast=fc)


def _f(v):
    try: return float(v) if v and str(v).strip() else None
    except: return None


def _compute_trust(farmer_id):
    txns = db.session.execute(
        text("SELECT * FROM transactions WHERE farmer_id = :fid"),
        {'fid': farmer_id}
    ).fetchall()
    completed = [t for t in txns if t.status == 'completed']
    on_time   = [t for t in completed if t.is_on_time]
    delivery_rate = (len(on_time) / len(completed) * 100) if completed else None

    ratings = db.session.execute(
        text("SELECT * FROM ratings WHERE farmer_id = :fid"),
        {'fid': farmer_id}
    ).fetchall()
    rating_avg = (sum(r.score for r in ratings) / len(ratings)) if ratings else None

    active_q = db.session.execute(
        text("SELECT AVG(quality_score_live) FROM produce_listings WHERE farmer_id = :fid AND status = 'active'"),
        {'fid': farmer_id}
    ).scalar()
    listing_quality = float(active_q) if active_q else None

    parts, weights = [], []
    if delivery_rate   is not None: parts.append(delivery_rate / 100);   weights.append(0.40)
    if rating_avg      is not None: parts.append((rating_avg - 1) / 4);  weights.append(0.40)
    if listing_quality is not None: parts.append(listing_quality / 100); weights.append(0.20)

    if parts:
        total_w = sum(weights)
        final = sum(p * w for p, w in zip(parts, weights)) / total_w
    else:
        row = db.session.execute(
            text("SELECT trust_score FROM users WHERE id = :fid"),
            {'fid': farmer_id}
        ).fetchone()
        final = float(row.trust_score or 0) if row else 0.0

    return {
        'total_transactions':     len(txns),
        'completed_transactions': len(completed),
        'on_time_transactions':   len(on_time),
        'delivery_rate':          delivery_rate,
        'rating_avg':             rating_avg,
        'rating_count':           len(ratings),
        'listing_quality':        listing_quality,
        'final_score':            round(final, 2),
        'final_pct':              round(final * 100),
    }


# ══════════════════════════════════════════════════════════════
# DASHBOARD
# ══════════════════════════════════════════════════════════════

@farmer_bp.route('/dashboard')
@login_required
@farmer_required
def dashboard():
    f = current_user
    farms = db.session.execute(
        text("SELECT * FROM farms WHERE owner_id = :uid ORDER BY created_at"),
        {'uid': f.id}
    ).fetchall()

    fid = request.args.get('farm_id', type=int)
    sf = None
    if fid:
        sf = db.session.execute(
            text("SELECT * FROM farms WHERE id = :fid AND owner_id = :uid"),
            {'fid': fid, 'uid': f.id}
        ).fetchone()
    if not sf and farms:
        sf = farms[0]

    lr = None
    if sf:
        lr = db.session.execute(
            text("SELECT * FROM sensor_readings WHERE farm_id = :fid ORDER BY timestamp DESC LIMIT 1"),
            {'fid': sf.id}
        ).fetchone()

    ss  = _status(lr)
    ago = _ago(lr.timestamp) if lr else 'never'
    qs  = sf.current_quality_score if sf else None
    qd  = _qdetail(lr)

    afc = None
    if sf:
        afc = db.session.execute(
            text("SELECT * FROM harvest_forecasts WHERE farm_id = :fid AND is_active = 1 ORDER BY created_at DESC LIMIT 1"),
            {'fid': sf.id}
        ).fetchone()

    als = db.session.execute(
        text("SELECT * FROM produce_listings WHERE farmer_id = :uid AND status = 'active' ORDER BY created_at DESC LIMIT 5"),
        {'uid': f.id}
    ).fetchall()

    ac = db.session.execute(
        text("SELECT COUNT(*) FROM produce_listings WHERE farmer_id = :uid AND status = 'active'"),
        {'uid': f.id}
    ).scalar()

    ral = db.session.execute(
        text("SELECT * FROM notifications WHERE recipient_id = :uid ORDER BY sent_at DESC LIMIT 5"),
        {'uid': f.id}
    ).fetchall()

    un = db.session.execute(
        text("SELECT COUNT(*) FROM notifications WHERE recipient_id = :uid AND is_read = 0"),
        {'uid': f.id}
    ).scalar()

    return render_template('farmer/dashboard.html',
        farmer=f, now=datetime.utcnow(),
        farms=farms, selected_farm=sf,
        latest_reading=lr, sensor_status=ss, last_reading_ago=ago,
        quality_score=qs, quality_detail=qd,
        active_forecast=afc, active_listings=als, active_count=ac,
        recent_alerts=ral, unread_notifs=un,
        active_page='dashboard',
    )


# ══════════════════════════════════════════════════════════════
# MY FARMS
# ══════════════════════════════════════════════════════════════

@farmer_bp.route('/farms')
@login_required
@farmer_required
def farms():
    farm_list = db.session.execute(
        text("SELECT * FROM farms WHERE owner_id = :uid ORDER BY created_at"),
        {'uid': current_user.id}
    ).fetchall()

    farms_data = []
    for farm in farm_list:
        lr = db.session.execute(
            text("SELECT * FROM sensor_readings WHERE farm_id = :fid ORDER BY timestamp DESC LIMIT 1"),
            {'fid': farm.id}
        ).fetchone()
        listing_count = db.session.execute(
            text("SELECT COUNT(*) FROM produce_listings WHERE farm_id = :fid AND farmer_id = :uid AND status = 'active'"),
            {'fid': farm.id, 'uid': current_user.id}
        ).scalar()
        reading_count = db.session.execute(
            text("SELECT COUNT(*) FROM sensor_readings WHERE farm_id = :fid"),
            {'fid': farm.id}
        ).scalar()
        farms_data.append({'farm': farm, 'latest_reading': lr,
                           'listing_count': listing_count, 'reading_count': reading_count})

    return render_template('farmer/farms.html', active_page='farms',
                           now=datetime.utcnow(), farm_list=farm_list,
                           farms_data=farms_data, **_sidebar(current_user))


# ══════════════════════════════════════════════════════════════
# ADD / EDIT / DELETE FARM
# ══════════════════════════════════════════════════════════════

@farmer_bp.route('/farms/new', methods=['GET', 'POST'])
@login_required
@farmer_required
def add_farm():
    ctx = _sidebar(current_user)
    if request.method == 'POST':
        frm   = request.form; errors = {}
        name  = frm.get('farm_name', '').strip()
        reg   = frm.get('region', '').strip()
        crop  = frm.get('crop_type', '').strip()
        town  = frm.get('town', '').strip() or None
        nid   = frm.get('sensor_node_id', '').strip().upper() or None
        notes = frm.get('notes', '').strip() or None
        sh    = _f(frm.get('size_hectares'))
        lat   = _f(frm.get('latitude'))
        lng   = _f(frm.get('longitude'))

        if not name:               errors['farm_name']      = 'Farm name is required.'
        elif len(name) > 100:      errors['farm_name']      = 'Must be under 100 characters.'
        if not reg or reg not in _REGIONS: errors['region'] = 'Please select a valid region.'
        if not crop:               errors['crop_type']      = 'Please select a primary crop.'
        if nid:
            clash = db.session.execute(
                text("SELECT owner_id FROM farms WHERE sensor_node_id = :nid"),
                {'nid': nid}
            ).fetchone()
            if clash and clash.owner_id != current_user.id:
                errors['sensor_node_id'] = f'{nid} is already linked to another farm.'

        if errors:
            return render_template('farmer/add_farm.html', form_errors=errors,
                                   form_data=frm, active_page='farms', **ctx)

        db.session.execute(
            text("""
                INSERT INTO farms
                    (owner_id, name, region, town, crop_type, size_hectares,
                     latitude, longitude, sensor_node_id, notes, created_at)
                VALUES
                    (:owner_id, :name, :region, :town, :crop_type, :size_hectares,
                     :latitude, :longitude, :sensor_node_id, :notes, :created_at)
            """),
            {'owner_id': current_user.id, 'name': name, 'region': reg,
             'town': town, 'crop_type': crop, 'size_hectares': sh,
             'latitude': lat, 'longitude': lng, 'sensor_node_id': nid,
             'notes': notes, 'created_at': datetime.utcnow()}
        )
        db.session.commit()
        flash(f'Farm "{name}" added successfully.', 'success')
        return redirect(url_for('farmer.farms'))

    return render_template('farmer/add_farm.html', form_errors=None,
                           form_data=None, active_page='farms', **ctx)


@farmer_bp.route('/farms/<int:farm_id>', methods=['GET', 'POST'])
@login_required
@farmer_required
def edit_farm(farm_id):
    farm = db.session.execute(
        text("SELECT * FROM farms WHERE id = :fid AND owner_id = :uid"),
        {'fid': farm_id, 'uid': current_user.id}
    ).fetchone()
    if not farm:
        flash('Farm not found or access denied.', 'error')
        return redirect(url_for('farmer.farms'))

    lr = db.session.execute(
        text("SELECT * FROM sensor_readings WHERE farm_id = :fid ORDER BY timestamp DESC LIMIT 1"),
        {'fid': farm.id}
    ).fetchone()
    ss  = _status(lr)
    ctx = _sidebar(current_user)

    if request.method == 'POST':
        frm   = request.form; errors = {}
        name  = frm.get('farm_name', '').strip()
        reg   = frm.get('region', '').strip()
        crop  = frm.get('crop_type', '').strip()
        town  = frm.get('town', '').strip() or None
        nid   = frm.get('sensor_node_id', '').strip().upper() or None
        notes = frm.get('notes', '').strip() or None
        sh    = _f(frm.get('size_hectares'))
        lat   = _f(frm.get('latitude'))
        lng   = _f(frm.get('longitude'))

        if not name: errors['farm_name'] = 'Farm name is required.'
        if not reg or reg not in _REGIONS: errors['region'] = 'Please select a valid region.'
        if not crop: errors['crop_type'] = 'Please select a primary crop.'
        if nid and nid != farm.sensor_node_id:
            clash = db.session.execute(
                text("SELECT id FROM farms WHERE sensor_node_id = :nid"),
                {'nid': nid}
            ).fetchone()
            if clash:
                errors['sensor_node_id'] = f'{nid} is already linked to another farm.'

        if errors:
            return render_template('farmer/edit_farm.html', farm=farm,
                                   form_errors=errors, latest_reading=lr,
                                   sensor_status=ss, active_page='farms', **ctx)

        db.session.execute(
            text("""
                UPDATE farms SET
                    name = :name, region = :region, town = :town,
                    crop_type = :crop_type, size_hectares = :size_hectares,
                    latitude = :latitude, longitude = :longitude,
                    sensor_node_id = :sensor_node_id, notes = :notes
                WHERE id = :fid
            """),
            {'name': name, 'region': reg, 'town': town, 'crop_type': crop,
             'size_hectares': sh, 'latitude': lat, 'longitude': lng,
             'sensor_node_id': nid, 'notes': notes, 'fid': farm_id}
        )
        db.session.commit()
        flash(f'"{name}" updated successfully.', 'success')
        return redirect(url_for('farmer.farms'))

    return render_template('farmer/edit_farm.html', farm=farm, form_errors=None,
                           latest_reading=lr, sensor_status=ss, active_page='farms', **ctx)


@farmer_bp.route('/farms/<int:farm_id>/delete', methods=['POST'])
@login_required
@farmer_required
def delete_farm(farm_id):
    farm = db.session.execute(
        text("SELECT name FROM farms WHERE id = :fid AND owner_id = :uid"),
        {'fid': farm_id, 'uid': current_user.id}
    ).fetchone()
    if not farm:
        flash('Farm not found.', 'error')
        return redirect(url_for('farmer.farms'))

    name = farm.name
    db.session.execute(text("DELETE FROM farms WHERE id = :fid"), {'fid': farm_id})
    db.session.commit()
    flash(f'Farm "{name}" has been deleted.', 'success')
    return redirect(url_for('farmer.farms'))


# ══════════════════════════════════════════════════════════════
# LISTINGS
# ══════════════════════════════════════════════════════════════

class _SimplePagination:
    """Minimal pagination object compatible with Jinja templates."""
    def __init__(self, items, page, per_page, total):
        self.items    = items
        self.page     = page
        self.per_page = per_page
        self.total    = total
        self.pages    = max(1, -(-total // per_page))
        self.has_prev = page > 1
        self.has_next = page < self.pages
        self.prev_num = page - 1
        self.next_num = page + 1

    def iter_pages(self, left_edge=2, right_edge=2, left_current=2, right_current=2):
        last = 0
        for num in range(1, self.pages + 1):
            if (num <= left_edge
                    or (self.page - left_current - 1 < num < self.page + right_current)
                    or num > self.pages - right_edge):
                if last + 1 != num:
                    yield None
                yield num
                last = num


@farmer_bp.route('/listings')
@login_required
@farmer_required
def listings():
    status_filter = request.args.get('status', 'all')
    page     = request.args.get('page', 1, type=int)
    per_page = 15
    offset   = (page - 1) * per_page

    if status_filter in ('draft', 'active', 'sold', 'delisted'):
        rows = db.session.execute(
            text("SELECT * FROM produce_listings WHERE farmer_id = :uid AND status = :s ORDER BY created_at DESC LIMIT :lim OFFSET :off"),
            {'uid': current_user.id, 's': status_filter, 'lim': per_page, 'off': offset}
        ).fetchall()
        total = db.session.execute(
            text("SELECT COUNT(*) FROM produce_listings WHERE farmer_id = :uid AND status = :s"),
            {'uid': current_user.id, 's': status_filter}
        ).scalar()
    else:
        rows = db.session.execute(
            text("SELECT * FROM produce_listings WHERE farmer_id = :uid ORDER BY created_at DESC LIMIT :lim OFFSET :off"),
            {'uid': current_user.id, 'lim': per_page, 'off': offset}
        ).fetchall()
        total = db.session.execute(
            text("SELECT COUNT(*) FROM produce_listings WHERE farmer_id = :uid"),
            {'uid': current_user.id}
        ).scalar()

    pagination = _SimplePagination(rows, page, per_page, total)

    counts = {}
    for s in ('draft', 'active', 'sold', 'delisted'):
        counts[s] = db.session.execute(
            text("SELECT COUNT(*) FROM produce_listings WHERE farmer_id = :uid AND status = :s"),
            {'uid': current_user.id, 's': s}
        ).scalar()
    counts['all'] = sum(counts.values())

    farm_rows = db.session.execute(
        text("SELECT * FROM farms WHERE owner_id = :uid"),
        {'uid': current_user.id}
    ).fetchall()
    farm_map = {f.id: f for f in farm_rows}

    return render_template('farmer/listings.html', active_page='listings',
                           listing_list=pagination.items, pagination=pagination,
                           status_filter=status_filter, counts=counts,
                           farm_map=farm_map, **_sidebar(current_user))


@farmer_bp.route('/listings/new', methods=['GET', 'POST'])
@login_required
@farmer_required
def new_listing():
    ctx   = _sidebar(current_user)
    farms = db.session.execute(
        text("SELECT * FROM farms WHERE owner_id = :uid ORDER BY name"),
        {'uid': current_user.id}
    ).fetchall()

    if request.method == 'POST':
        frm         = request.form; errors = {}
        farm_id     = frm.get('farm_id', type=int)
        crop_type   = frm.get('crop_type', '').strip()
        qty         = _f(frm.get('quantity_kg'))
        price       = _f(frm.get('price_per_kg'))
        min_order   = _f(frm.get('min_order_kg'))
        description = frm.get('description', '').strip() or None
        status      = frm.get('status', 'draft')

        if not farm_id:
            errors['farm_id'] = 'Please select a farm.'
        else:
            valid_farm = db.session.execute(
                text("SELECT id FROM farms WHERE id = :fid AND owner_id = :uid"),
                {'fid': farm_id, 'uid': current_user.id}
            ).fetchone()
            if not valid_farm:
                errors['farm_id'] = 'Invalid farm selected.'

        if not crop_type:          errors['crop_type']    = 'Crop type is required.'
        if not qty or qty <= 0:    errors['quantity_kg']  = 'Enter a quantity greater than 0.'
        if not price or price <= 0:errors['price_per_kg'] = 'Enter a price greater than 0.'
        if status not in ('draft', 'active'): status = 'draft'

        if errors:
            return render_template('farmer/listing_new.html', form_errors=errors,
                                   form_data=frm, farms=farms, crops=_CROPS,
                                   active_page='listings', **ctx)

        farm_row = db.session.execute(
            text("SELECT current_quality_score FROM farms WHERE id = :fid"),
            {'fid': farm_id}
        ).fetchone()
        quality_snap = farm_row.current_quality_score or 0

        now = datetime.utcnow()
        result = db.session.execute(
            text("""
                INSERT INTO produce_listings
                    (farmer_id, farm_id, crop_type, quantity_kg, price_per_kg,
                     min_order_kg, description, status,
                     quality_score_at_listing, quality_score_live,
                     inquiry_count, created_at, updated_at)
                VALUES
                    (:farmer_id, :farm_id, :crop_type, :qty, :price,
                     :min_order, :desc, :status,
                     :qsnap, :qsnap,
                     0, :now, :now)
            """),
            {'farmer_id': current_user.id, 'farm_id': farm_id, 'crop_type': crop_type,
             'qty': qty, 'price': price, 'min_order': min_order, 'desc': description,
             'status': status, 'qsnap': quality_snap, 'now': now}
        )
        db.session.flush()
        listing_id = result.lastrowid

        if status == 'active':
            db.session.execute(
                text("""
                    INSERT INTO notifications
                        (recipient_id, type, title, message, listing_id, channel, is_read, sent_at)
                    VALUES
                        (:uid, 'listing_published', 'Listing published', :msg, :lid, 'web', 0, :now)
                """),
                {'uid': current_user.id,
                 'msg': f'Your listing for {crop_type} ({qty} kg at XAF {price}/kg) is now live.',
                 'lid': listing_id, 'now': now}
            )
            db.session.commit()
            flash(f'Listing for {crop_type} published successfully.', 'success')
        else:
            db.session.commit()
            flash(f'Listing for {crop_type} saved as draft.', 'success')

        return redirect(url_for('farmer.listings'))

    return render_template('farmer/listing_new.html', form_errors=None, form_data=None,
                           farms=farms, crops=_CROPS, active_page='listings', **ctx)


@farmer_bp.route('/listings/<int:lid>', methods=['GET', 'POST'])
@login_required
@farmer_required
def edit_listing(lid):
    listing = db.session.execute(
        text("SELECT * FROM produce_listings WHERE id = :lid AND farmer_id = :uid"),
        {'lid': lid, 'uid': current_user.id}
    ).fetchone()
    if not listing:
        flash('Listing not found or access denied.', 'error')
        return redirect(url_for('farmer.listings'))

    ctx   = _sidebar(current_user)
    farms = db.session.execute(
        text("SELECT * FROM farms WHERE owner_id = :uid ORDER BY name"),
        {'uid': current_user.id}
    ).fetchall()
    enquiries = db.session.execute(
        text("SELECT * FROM contact_requests WHERE listing_id = :lid AND farmer_id = :uid ORDER BY created_at DESC"),
        {'lid': lid, 'uid': current_user.id}
    ).fetchall()

    if request.method == 'POST':
        frm    = request.form
        action = frm.get('action', 'save')
        now    = datetime.utcnow()

        if action == 'publish' and listing.status == 'draft':
            db.session.execute(
                text("UPDATE produce_listings SET status = 'active', updated_at = :now WHERE id = :lid"),
                {'now': now, 'lid': lid}
            )
            db.session.commit()
            flash('Listing is now live on the marketplace.', 'success')
            return redirect(url_for('farmer.listings'))

        if action == 'delist' and listing.status == 'active':
            db.session.execute(
                text("UPDATE produce_listings SET status = 'delisted', updated_at = :now WHERE id = :lid"),
                {'now': now, 'lid': lid}
            )
            db.session.commit()
            flash('Listing has been delisted.', 'success')
            return redirect(url_for('farmer.listings'))

        if action == 'republish' and listing.status == 'delisted':
            db.session.execute(
                text("UPDATE produce_listings SET status = 'active', updated_at = :now WHERE id = :lid"),
                {'now': now, 'lid': lid}
            )
            db.session.commit()
            flash('Listing is active again.', 'success')
            return redirect(url_for('farmer.listings'))

        errors      = {}
        crop_type   = frm.get('crop_type', '').strip()
        qty         = _f(frm.get('quantity_kg'))
        price       = _f(frm.get('price_per_kg'))
        min_order   = _f(frm.get('min_order_kg'))
        description = frm.get('description', '').strip() or None

        if not crop_type:          errors['crop_type']    = 'Crop type is required.'
        if not qty or qty <= 0:    errors['quantity_kg']  = 'Enter a quantity greater than 0.'
        if not price or price <= 0:errors['price_per_kg'] = 'Enter a price greater than 0.'

        if errors:
            return render_template('farmer/listing_edit.html', listing=listing,
                                   form_errors=errors, farms=farms, crops=_CROPS,
                                   enquiries=enquiries, active_page='listings', **ctx)

        db.session.execute(
            text("""
                UPDATE produce_listings SET
                    crop_type = :crop_type, quantity_kg = :qty,
                    price_per_kg = :price, min_order_kg = :min_order,
                    description = :desc, updated_at = :now
                WHERE id = :lid
            """),
            {'crop_type': crop_type, 'qty': qty, 'price': price,
             'min_order': min_order, 'desc': description, 'now': now, 'lid': lid}
        )
        db.session.commit()
        flash('Listing updated.', 'success')
        return redirect(url_for('farmer.listings'))

    return render_template('farmer/listing_edit.html', listing=listing,
                           form_errors=None, farms=farms, crops=_CROPS,
                           enquiries=enquiries, active_page='listings', **ctx)


@farmer_bp.route('/listings/<int:lid>/delete', methods=['POST'])
@login_required
@farmer_required
def delete_listing(lid):
    listing = db.session.execute(
        text("SELECT * FROM produce_listings WHERE id = :lid AND farmer_id = :uid"),
        {'lid': lid, 'uid': current_user.id}
    ).fetchone()
    if not listing:
        flash('Listing not found.', 'error')
        return redirect(url_for('farmer.listings'))
    if listing.status not in ('draft', 'delisted'):
        flash('Only draft or delisted listings can be deleted.', 'error')
        return redirect(url_for('farmer.listings'))

    crop = listing.crop_type
    db.session.execute(text("DELETE FROM produce_listings WHERE id = :lid"), {'lid': lid})
    db.session.commit()
    flash(f'Listing for {crop} deleted.', 'success')
    return redirect(url_for('farmer.listings'))


# ══════════════════════════════════════════════════════════════
# FORECAST DETAIL
# ══════════════════════════════════════════════════════════════

@farmer_bp.route('/forecasts/<int:fid>')
@login_required
@farmer_required
def forecast_detail(fid):
    forecast = db.session.execute(
        text("""
            SELECT hf.*
            FROM harvest_forecasts hf
            JOIN farms f ON f.id = hf.farm_id
            WHERE hf.id = :fid AND f.owner_id = :uid
        """),
        {'fid': fid, 'uid': current_user.id}
    ).fetchone()
    if not forecast:
        flash('Forecast not found.', 'error')
        return redirect(url_for('farmer.dashboard'))

    farm = db.session.execute(
        text("SELECT * FROM farms WHERE id = :fid"),
        {'fid': forecast.farm_id}
    ).fetchone()

    readings = db.session.execute(
        text("SELECT * FROM sensor_readings WHERE farm_id = :fid ORDER BY timestamp ASC LIMIT 400"),
        {'fid': farm.id}
    ).fetchall()

    daily = defaultdict(lambda: {'sm': [], 'tmp': [], 'hum': []})
    for r in readings:
        d = r.timestamp.strftime('%b %d')
        if r.soil_moisture:  daily[d]['sm'].append(float(r.soil_moisture))
        if r.temperature:    daily[d]['tmp'].append(float(r.temperature))
        if r.humidity:       daily[d]['hum'].append(float(r.humidity))

    keys         = list(daily.keys())[-14:]
    chart_labels = keys
    chart_sm  = [round(sum(daily[d]['sm'])  / len(daily[d]['sm']),  1) if daily[d]['sm']  else 0 for d in keys]
    chart_tmp = [round(sum(daily[d]['tmp']) / len(daily[d]['tmp']), 1) if daily[d]['tmp'] else 0 for d in keys]
    chart_hum = [round(sum(daily[d]['hum']) / len(daily[d]['hum']), 1) if daily[d]['hum'] else 0 for d in keys]

    all_forecasts = db.session.execute(
        text("SELECT * FROM harvest_forecasts WHERE farm_id = :fid ORDER BY created_at DESC"),
        {'fid': farm.id}
    ).fetchall()

    today      = date.today()
    days_until = max((forecast.predicted_harvest_start - today).days, 0)

    return render_template('farmer/forecast_detail.html',
                           forecast=forecast, farm=farm, readings=readings,
                           chart_labels=chart_labels,
                           chart_sm=chart_sm, chart_tmp=chart_tmp, chart_hum=chart_hum,
                           all_forecasts=all_forecasts, days_until=days_until,
                           today=today, active_page='forecasts',
                           **_sidebar(current_user))


# ══════════════════════════════════════════════════════════════
# TRUST SCORE
# ══════════════════════════════════════════════════════════════

@farmer_bp.route('/trust')
@login_required
@farmer_required
def trust_score():
    trust = _compute_trust(current_user.id)

    recent_ratings = db.session.execute(
        text("SELECT * FROM ratings WHERE farmer_id = :uid ORDER BY created_at DESC LIMIT 10"),
        {'uid': current_user.id}
    ).fetchall()

    all_ratings = db.session.execute(
        text("SELECT score FROM ratings WHERE farmer_id = :uid"),
        {'uid': current_user.id}
        
    ).fetchall()
    dist = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for r in all_ratings:
        dist[r.score] = dist.get(r.score, 0) + 1

    recent_txns = db.session.execute(
        text("SELECT * FROM transactions WHERE farmer_id = :uid ORDER BY created_at DESC LIMIT 5"),
        {'uid': current_user.id}
    ).fetchall()

    return render_template('farmer/trust_score.html', trust=trust,
                           recent_ratings=recent_ratings, rating_dist=dist,
                           recent_txns=recent_txns, active_page='trust',
                           **_sidebar(current_user))


# ══════════════════════════════════════════════════════════════
# NOTIFICATIONS
# ══════════════════════════════════════════════════════════════

@farmer_bp.route('/notifications')
@login_required
@farmer_required
def notifications():
    page        = request.args.get('page', 1, type=int)
    type_filter = request.args.get('type', 'all')
    per_page    = 20
    offset      = (page - 1) * per_page

    if type_filter != 'all':
        rows = db.session.execute(
            text("SELECT * FROM notifications WHERE recipient_id = :uid AND type = :type ORDER BY sent_at DESC LIMIT :lim OFFSET :off"),
            {'uid': current_user.id, 'type': type_filter, 'lim': per_page, 'off': offset}
        ).fetchall()
        total = db.session.execute(
            text("SELECT COUNT(*) FROM notifications WHERE recipient_id = :uid AND type = :type"),
            {'uid': current_user.id, 'type': type_filter}
        ).scalar()
    else:
        rows = db.session.execute(
            text("SELECT * FROM notifications WHERE recipient_id = :uid ORDER BY sent_at DESC LIMIT :lim OFFSET :off"),
            {'uid': current_user.id, 'lim': per_page, 'off': offset}
        ).fetchall()
        total = db.session.execute(
            text("SELECT COUNT(*) FROM notifications WHERE recipient_id = :uid"),
            {'uid': current_user.id}
        ).scalar()

    # Mark all as read
    db.session.execute(
        text("UPDATE notifications SET is_read = 1 WHERE recipient_id = :uid AND is_read = 0"),
        {'uid': current_user.id}
    )
    db.session.commit()

    pagination = _SimplePagination(rows, page, per_page, total)

    notif_types = ['harvest_alert', 'sensor_offline', 'quality_change', 'account_verified',
                   'listing_published', 'transaction_completed', 'buyer_enquiry', 'system']

    active_fc = db.session.execute(
        text("""
            SELECT hf.* FROM harvest_forecasts hf
            JOIN farms f ON f.id = hf.farm_id
            WHERE f.owner_id = :uid AND hf.is_active = 1
            ORDER BY hf.created_at DESC LIMIT 1
        """),
        {'uid': current_user.id}
    ).fetchone()

    return render_template('farmer/notifications.html',
                           notif_list=pagination.items, pagination=pagination,
                           type_filter=type_filter, notif_types=notif_types,
                           active_page='notifications', unread_notifs=0,
                           active_forecast=active_fc)


@farmer_bp.route('/notifications/<int:nid>/read', methods=['POST'])
@login_required
@farmer_required
def mark_notification_read(nid):
    db.session.execute(
        text("UPDATE notifications SET is_read = 1 WHERE id = :nid AND recipient_id = :uid"),
        {'nid': nid, 'uid': current_user.id}
    )
    db.session.commit()
    return jsonify({'ok': True})


# ══════════════════════════════════════════════════════════════
# PROFILE
# ══════════════════════════════════════════════════════════════

@farmer_bp.route('/profile', methods=['GET', 'POST'])
@login_required
@farmer_required
def profile():
    ctx = _sidebar(current_user)
    if request.method == 'POST':
        frm          = request.form; errors = {}
        full_name    = frm.get('full_name', '').strip()
        phone        = frm.get('phone', '').strip() or None
        region       = frm.get('region', '').strip()
        primary_crop = frm.get('primary_crop', '').strip() or None

        if not full_name:          errors['full_name'] = 'Name is required.'
        elif len(full_name) > 100: errors['full_name'] = 'Must be under 100 characters.'
        if region and region not in _REGIONS: errors['region'] = 'Please select a valid region.'

        if errors:
            return render_template('farmer/profile.html', form_errors=errors,
                                   regions=_REGIONS, crops=_CROPS,
                                   active_page='profile', **ctx)

        db.session.execute(
            text("""
                UPDATE users SET
                    full_name    = :full_name,
                    phone        = :phone,
                    region       = COALESCE(:region, region),
                    primary_crop = :primary_crop,
                    updated_at   = :now
                WHERE id = :uid
            """),
            {'full_name': full_name, 'phone': phone,
             'region': region or None, 'primary_crop': primary_crop,
             'now': datetime.utcnow(), 'uid': current_user.id}
        )
        db.session.commit()
        flash('Profile updated successfully.', 'success')
        return redirect(url_for('farmer.profile'))

    return render_template('farmer/profile.html', form_errors=None,
                           regions=_REGIONS, crops=_CROPS,
                           active_page='profile', **ctx)
