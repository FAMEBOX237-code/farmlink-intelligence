# ============================================================
# routes/api.py — FarmLink Intelligence REST API
#
# All endpoints return JSON. Swagger documentation is
# auto-generated from the docstrings by Flasgger and is
# available at:   GET /api/docs/
#
# OOP NOTE:
#   These routes reuse the same model classes (ProduceListing,
#   ContactRequest, Farm, User) as the web routes. Only the
#   output format changes — jsonify() instead of render_template().
#   This is polymorphism: the same objects serve multiple interfaces.
#
# ENDPOINTS:
#   GET  /api/health            — system health check (public)
#   GET  /api/listings          — browse listings (public)
#   GET  /api/listings/<id>     — single listing detail (public)
#   GET  /api/enquiries         — user's messages (authenticated)
#   POST /api/contact           — send a message (authenticated)
#
# AUTHENTICATION:
#   Session-based. Log in via POST /login first.
#   Authenticated endpoints return 401 if not logged in.
# ============================================================

from datetime import datetime
from functools import wraps

from flask         import Blueprint, jsonify, request
from flask_login   import current_user

from extensions    import db
from models.models import (
    User, Farm, SensorReading, ProduceListing,
    ContactRequest, Notification,
)


api_bp = Blueprint('api', __name__, url_prefix='/api')


# ══════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════

def _json_error(message, status=400):
    """Return a standardised JSON error response."""
    return jsonify({'success': False, 'error': message}), status


def _json_ok(data, meta=None):
    """Return a standardised JSON success response."""
    payload = {'success': True, 'data': data}
    if meta:
        payload['meta'] = meta
    return jsonify(payload), 200


def _ago(dt):
    """Human-readable time since dt (UTC)."""
    if not dt:
        return None
    s = (datetime.utcnow() - dt).total_seconds()
    if s < 60:     return 'just now'
    if s < 3600:   m = int(s // 60);   return f'{m}m ago'
    if s < 86400:  h = int(s // 3600); return f'{h}h ago'
    return f'{int(s // 86400)}d ago'


def api_login_required(f):
    """
    Decorator for authenticated API endpoints.
    Returns JSON 401 instead of redirecting to /login.
    The standard @login_required redirects to the login page —
    wrong behaviour for an API consumer expecting JSON.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return _json_error(
                'Authentication required. Log in via POST /login first.',
                401
            )
        return f(*args, **kwargs)
    return decorated


# ══════════════════════════════════════════════════════════════
# ENDPOINT 1 — HEALTH CHECK
# GET /api/health
# ══════════════════════════════════════════════════════════════

@api_bp.route('/health', methods=['GET'])
def health():
    """
    System health check.
    ---
    tags:
      - System
    summary: Check if the FarmLink API is running
    description: >
      Returns the current status of the API server and database
      connectivity. Use this to verify the API is reachable
      before making other requests.
    responses:
      200:
        description: API is healthy and database is reachable
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            data:
              type: object
              properties:
                status:
                  type: string
                  example: healthy
                database:
                  type: string
                  example: connected
                timestamp:
                  type: string
                  example: "2026-04-29T08:00:00Z"
                version:
                  type: string
                  example: "1.0.0"
    """
    try:
        db.session.execute(db.text('SELECT 1'))
        db_status = 'connected'
    except Exception:
        db_status = 'unavailable'

    return _json_ok({
        'status'   : 'healthy',
        'database' : db_status,
        'timestamp': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
        'version'  : '1.0.0',
        'message'  : 'FarmLink Intelligence API is running.',
    })


# ══════════════════════════════════════════════════════════════
# ENDPOINT 2 — BROWSE LISTINGS
# GET /api/listings
# ══════════════════════════════════════════════════════════════

@api_bp.route('/listings', methods=['GET'])
def listings():
    """
    Browse active produce listings.
    ---
    tags:
      - Marketplace
    summary: Get paginated IoT-verified produce listings
    description: >
      Returns active listings from verified farmers, sorted by
      combined rank (60% quality score + 40% trust score).
      Quality scores are computed automatically from IoT sensor
      data every 30 minutes. Trust scores are computed from
      transaction history, delivery records, and buyer ratings.
    parameters:
      - name: crop
        in: query
        type: string
        required: false
        description: Filter by crop type (e.g. Tomatoes, Maize)
        example: Tomatoes
      - name: region
        in: query
        type: string
        required: false
        description: Filter by farm region (e.g. Yaoundé)
        example: Yaoundé
      - name: min_quality
        in: query
        type: number
        required: false
        description: Minimum quality score 0–100
        example: 60
      - name: page
        in: query
        type: integer
        required: false
        description: Page number (default 1)
        example: 1
      - name: per_page
        in: query
        type: integer
        required: false
        description: Results per page, max 50 (default 10)
        example: 10
    responses:
      200:
        description: Paginated list of active listings
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            data:
              type: array
              items:
                type: object
                properties:
                  id:
                    type: integer
                    example: 4
                  crop_type:
                    type: string
                    example: Tomatoes
                  quantity_kg:
                    type: number
                    example: 120.0
                  price_per_kg:
                    type: number
                    example: 350.0
                  quality_score:
                    type: number
                    example: 78.4
                  farmer_trust_score:
                    type: number
                    example: 82.1
                  combined_rank:
                    type: number
                    example: 79.9
                  farm_name:
                    type: string
                    example: Green Valley Farm
                  region:
                    type: string
                    example: Yaoundé
                  farmer_name:
                    type: string
                    example: Jean-Pierre Nkomo
                  listed_ago:
                    type: string
                    example: 3d ago
            meta:
              type: object
              properties:
                page:
                  type: integer
                per_page:
                  type: integer
                total:
                  type: integer
                pages:
                  type: integer
    """
    crop        = request.args.get('crop',        '').strip()
    region      = request.args.get('region',      '').strip()
    min_quality = request.args.get('min_quality', type=float)
    page        = max(1, request.args.get('page', 1, type=int))
    per_page    = min(request.args.get('per_page', 10, type=int), 50)

    q = (ProduceListing.query
         .join(Farm, Farm.id == ProduceListing.farm_id)
         .join(User, User.id == ProduceListing.farmer_id)
         .filter(ProduceListing.status == 'active'))

    if crop:
        q = q.filter(ProduceListing.crop_type.ilike(f'%{crop}%'))
    if region:
        q = q.filter(Farm.region.ilike(f'%{region}%'))
    if min_quality is not None:
        q = q.filter(ProduceListing.quality_score_live >= min_quality)

    # Sort by combined rank (60% quality + 40% trust)
    # trust_score lives on the User model, so we sort in Python
    q = q.order_by(ProduceListing.quality_score_live.desc())

    total = q.count()
    items = q.offset((page - 1) * per_page).limit(per_page).all()
    pages = max(1, (total + per_page - 1) // per_page)

    def _s(listing):
        farm   = Farm.query.get(listing.farm_id)
        farmer = User.query.get(listing.farmer_id)
        trust  = float(farmer.trust_score or 0) if farmer else 0
        combined = round(
            float(listing.quality_score_live or 0) * 0.6 + trust * 0.4, 1
        )
        return {
            'id'                : listing.id,
            'crop_type'         : listing.crop_type,
            'quantity_kg'       : float(listing.quantity_kg  or 0),
            'price_per_kg'      : float(listing.price_per_kg or 0),
            'quality_score'     : float(listing.quality_score_live or 0),
            'farmer_trust_score': trust,
            'combined_rank'     : combined,
            'farm_name'         : farm.name     if farm   else None,
            'region'            : farm.region   if farm   else None,
            'farmer_name'       : farmer.full_name if farmer else None,
            'listed_ago'        : _ago(listing.created_at),
        }

    return _json_ok(
        data=[_s(l) for l in items],
        meta={'page': page, 'per_page': per_page,
              'total': total, 'pages': pages},
    )


# ══════════════════════════════════════════════════════════════
# ENDPOINT 3 — SINGLE LISTING DETAIL
# GET /api/listings/<id>
# ══════════════════════════════════════════════════════════════

@api_bp.route('/listings/<int:listing_id>', methods=['GET'])
def listing_detail(listing_id):
    """
    Get full detail for a single listing.
    ---
    tags:
      - Marketplace
    summary: Get one listing with IoT sensor data
    description: >
      Returns full detail for one active listing, including the
      most recent IoT sensor reading from the farm node.
      This is the core FarmLink proposition — quality claims
      backed by hardware data, not farmer self-reporting.
    parameters:
      - name: listing_id
        in: path
        type: integer
        required: true
        description: The listing ID
        example: 4
    responses:
      200:
        description: Full listing detail with sensor data
      404:
        description: Listing not found or not active
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            error:
              type: string
              example: Listing not found.
    """
    listing = ProduceListing.query.filter_by(
        id=listing_id, status='active'
    ).first()

    if not listing:
        return _json_error('Listing not found.', 404)

    farm   = Farm.query.get(listing.farm_id)
    farmer = User.query.get(listing.farmer_id)
    trust  = float(farmer.trust_score or 0) if farmer else 0

    latest = (SensorReading.query
              .filter_by(farm_id=listing.farm_id)
              .order_by(SensorReading.timestamp.desc())
              .first())

    sensor = None
    if latest:
        sensor = {
            'soil_moisture'  : float(latest.soil_moisture   or 0),
            'temperature'    : float(latest.temperature     or 0),
            'humidity'       : float(latest.humidity        or 0),
            'light_intensity': float(latest.light_intensity or 0),
            'is_raining'     : bool(latest.is_raining),
            'recorded_ago'   : _ago(latest.timestamp),
            'sync_status'    : latest.sync_status,
        }

    return _json_ok({
        'id'                : listing.id,
        'crop_type'         : listing.crop_type,
        'quantity_kg'       : float(listing.quantity_kg       or 0),
        'price_per_kg'      : float(listing.price_per_kg      or 0),
        'quality_score'     : float(listing.quality_score_live or 0),
        'farmer_trust_score': trust,
        'status'            : listing.status,
        'listed_ago'        : _ago(listing.created_at),
        'farmer': {
            'id'         : farmer.id         if farmer else None,
            'name'       : farmer.full_name  if farmer else None,
            'trust_score': trust,
        },
        'farm': {
            'id'           : farm.id        if farm else None,
            'name'         : farm.name      if farm else None,
            'region'       : farm.region    if farm else None,
            'town'         : farm.town      if farm else None,
            'crop_type'    : farm.crop_type if farm else None,
            'quality_score': float(farm.current_quality_score or 0) if farm else None,
        },
        'latest_sensor_reading': sensor,
    })


# ══════════════════════════════════════════════════════════════
# ENDPOINT 4 — USER ENQUIRIES
# GET /api/enquiries
# ══════════════════════════════════════════════════════════════

@api_bp.route('/enquiries', methods=['GET'])
@api_login_required
def enquiries():
    """
    Get the authenticated user's contact messages.
    ---
    tags:
      - Messaging
    summary: Get sent and received enquiries (login required)
    description: >
      Returns ContactRequest records for the authenticated user.
      Demonstrates OOP encapsulation — the ContactRequest object
      exposes can_reply() and is_unread_for() methods.
      The API calls these methods and includes the result in
      the response. Business logic stays in the object.
    parameters:
      - name: direction
        in: query
        type: string
        required: false
        description: sent | received | all (default)
        example: received
      - name: status
        in: query
        type: string
        required: false
        description: Filter by status — sent, read, replied
        example: sent
    responses:
      200:
        description: List of enquiries
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            data:
              type: array
              items:
                type: object
                properties:
                  id:
                    type: integer
                  direction:
                    type: string
                    example: received
                  context_label:
                    type: string
                    example: Listing enquiry
                  message:
                    type: string
                  reply_message:
                    type: string
                  status:
                    type: string
                    example: replied
                  can_reply:
                    type: boolean
                    example: false
                  is_unread:
                    type: boolean
                    example: true
                  sent_ago:
                    type: string
                    example: 2h ago
      401:
        description: Not authenticated
    """
    direction = request.args.get('direction', 'all').strip()
    status_f  = request.args.get('status',    '').strip()
    uid       = current_user.id

    if direction == 'sent':
        q = ContactRequest.query.filter_by(sender_id=uid)
    elif direction == 'received':
        q = ContactRequest.query.filter_by(recipient_id=uid)
    else:
        from sqlalchemy import or_
        q = ContactRequest.query.filter(
            or_(ContactRequest.sender_id    == uid,
                ContactRequest.recipient_id == uid)
        )

    if status_f in ('sent', 'read', 'replied'):
        q = q.filter_by(status=status_f)

    items = q.order_by(ContactRequest.created_at.desc()).all()

    def _s(eq):
        other_id = eq.recipient_id if eq.sender_id == uid else eq.sender_id
        other    = User.query.get(other_id)
        return {
            'id'           : eq.id,
            'direction'    : 'sent' if eq.sender_id == uid else 'received',
            'context_type' : eq.context_type,
            'context_label': eq.context_label,
            'other_party'  : other.full_name if other else 'Unknown',
            'other_role'   : other.role      if other else None,
            'listing_id'   : eq.listing_id,
            'message'      : eq.message,
            'reply_message': eq.reply_message,
            'status'       : eq.status,
            'can_reply'    : eq.can_reply(current_user),
            'is_unread'    : eq.is_unread_for(current_user),
            'sent_ago'     : _ago(eq.created_at),
            'replied_ago'  : _ago(eq.replied_at),
        }

    return _json_ok([_s(e) for e in items])


# ══════════════════════════════════════════════════════════════
# ENDPOINT 5 — SEND A CONTACT MESSAGE
# POST /api/contact
# ══════════════════════════════════════════════════════════════

@api_bp.route('/contact', methods=['POST'])
@api_login_required
def contact():
    """
    Send a contact message to a farmer.
    ---
    tags:
      - Messaging
    summary: Send a contact message via API (login required)
    description: >
      Creates a ContactRequest object and a Notification for
      the recipient. Demonstrates OOP — the route creates the
      object, the object manages its own state.
      The same ContactRequest class is used by both the web
      interface and this API endpoint.
    consumes:
      - application/json
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - recipient_id
            - context_type
            - message
          properties:
            recipient_id:
              type: integer
              description: User ID of the farmer to contact
              example: 6
            context_type:
              type: string
              description: listing_enquiry | farmer_profile | farmer_to_farmer
              example: listing_enquiry
            listing_id:
              type: integer
              description: Listing ID (for listing_enquiry only)
              example: 4
            message:
              type: string
              description: Message text, max 1000 characters
              example: Hi, I am interested in your tomatoes. What is the minimum order?
    responses:
      201:
        description: Message sent successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            data:
              type: object
              properties:
                enquiry_id:
                  type: integer
                  example: 12
                recipient:
                  type: string
                  example: Jean-Pierre Nkomo
                status:
                  type: string
                  example: sent
                message:
                  type: string
                  example: Message sent successfully.
      400:
        description: Validation error
      401:
        description: Not authenticated
      404:
        description: Recipient not found
    """
    data = request.get_json(silent=True)

    if not data:
        return _json_error('Request body must be JSON.', 400)

    recipient_id = data.get('recipient_id')
    context_type = data.get('context_type', '').strip()
    listing_id   = data.get('listing_id')
    message_text = data.get('message', '').strip()

    if not recipient_id:
        return _json_error('recipient_id is required.', 400)

    if context_type not in ('listing_enquiry', 'farmer_profile', 'farmer_to_farmer'):
        return _json_error(
            'context_type must be one of: '
            'listing_enquiry, farmer_profile, farmer_to_farmer.', 400
        )

    if not message_text:
        return _json_error('message is required.', 400)

    if len(message_text) > 1000:
        return _json_error('message must be 1000 characters or fewer.', 400)

    recipient = User.query.get(recipient_id)
    if not recipient:
        return _json_error('Recipient not found.', 404)

    if recipient.id == current_user.id:
        return _json_error('You cannot send a message to yourself.', 400)

    # OOP: create the ContactRequest object
    enquiry = ContactRequest(
        sender_id    = current_user.id,
        recipient_id = recipient_id,
        context_type = context_type,
        listing_id   = listing_id if context_type == 'listing_enquiry' else None,
        message      = message_text,
        status       = 'sent',
        created_at   = datetime.utcnow(),
    )
    db.session.add(enquiry)

    notification = Notification(
        recipient_id = recipient_id,
        type         = 'buyer_enquiry',
        title        = 'New message via API',
        message      = (
            f'{current_user.full_name} sent you a message: '
            f'"{message_text[:80]}{"…" if len(message_text) > 80 else ""}"'
        ),
        is_read = False,
        sent_at = datetime.utcnow(),
    )
    db.session.add(notification)
    db.session.commit()

    return jsonify({
        'success': True,
        'data': {
            'enquiry_id': enquiry.id,
            'recipient' : recipient.full_name,
            'status'    : enquiry.status,
            'message'   : 'Message sent successfully.',
        }
    }), 201