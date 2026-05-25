# ============================================================
# models/models.py — FarmLink Intelligence
#
# SQLAlchemy ORM models — every class here maps to one
# database table. Flask-SQLAlchemy handles creating,
# querying, and updating rows through these classes.
#
# IMPORT RULE:
#   Always import db from extensions, never from app.
#   This prevents circular imports.
#
# TABLE LIST:
#   User            — all accounts (farmer / buyer / admin)
#   Farm            — farms owned by farmers (+ IoT hardware identity fields)
#   SensorReading   — IoT sensor readings per farm (hardware schema)
#   Alert           — one row per alert event detected by the Python bridge
#   IrrigationLog   — per-event irrigation records from hardware schema
#   HarvestForecast — ML-style harvest window predictions
#   ProduceListing  — marketplace listings
#   Transaction     — completed buyer-farmer deals
#   Rating          — buyer ratings of farmers
#   BuyerAlert      — standing alert criteria per buyer
#   Notification    — in-app + email + SMS notifications
#   ContactRequest  — buyer enquiry messages to farmers
#
# SENSOR_READINGS / IRRIGATION_LOG — hardware schema (Phase 5.3):
#   reading_id      VARCHAR(30) PRIMARY KEY  (Arduino-generated)
#   farm_id         VARCHAR(50) FK → farms.hardware_farm_id
#   soil_moisture   DECIMAL(5,1)
#   sync_status     ENUM('BUFFERED','LIVE','SYNCED')  — hardware only
#   No light_intensity, no integer surrogate PK.
#
# ALERTS — hardware schema (Phase 5.6):
#   Written exclusively by the Python bridge.
#   The website reads alerts; it never writes them.
# ============================================================

from extensions import db
from flask_login import UserMixin
from datetime import datetime


# ══════════════════════════════════════════════════════════════
# USER
# Central account table — role determines which portal the
# user sees after login. Admins are created via seed.py only.
# ══════════════════════════════════════════════════════════════
class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id               = db.Column(db.Integer, primary_key=True)
    full_name        = db.Column(db.String(100), nullable=False)
    email            = db.Column(db.String(150), unique=True, nullable=False, index=True)
    password_hash    = db.Column(db.String(255), nullable=False)
    phone            = db.Column(db.String(20))
    role             = db.Column(db.Enum('farmer', 'buyer', 'admin'), nullable=False, default='buyer')
    region           = db.Column(db.String(50))
    primary_crop     = db.Column(db.String(100))
    trust_score      = db.Column(db.Numeric(3, 2), default=0.00)
    is_verified      = db.Column(db.Boolean, default=False, nullable=False)
    is_suspended     = db.Column(db.Boolean, default=False, nullable=False)
    profile_photo_url= db.Column(db.String(500))
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at       = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # ── Relationships ─────────────────────────────────────────
    farms    = db.relationship('Farm', backref='owner', lazy='dynamic',
                               cascade='all, delete-orphan',
                               foreign_keys='Farm.owner_id')
    listings = db.relationship('ProduceListing', backref='farmer', lazy='dynamic',
                               foreign_keys='ProduceListing.farmer_id')
    alerts   = db.relationship('BuyerAlert', backref='buyer', lazy='dynamic',
                               cascade='all, delete-orphan')

    # ── Role helpers ─────────────────────────────────────────
    def is_farmer(self): return self.role == 'farmer'
    def is_buyer(self):  return self.role == 'buyer'
    def is_admin(self):  return self.role == 'admin'

    # ── Flask-Login requires this ─────────────────────────────
    def get_id(self):
        return str(self.id)

    def __repr__(self):
        return f'<User {self.email} [{self.role}]>'


# ══════════════════════════════════════════════════════════════
# FARM
# Each farmer can own multiple farms. Each farm is linked
# to exactly one IoT sensor node via sensor_node_id.
#
# Hardware identity fields:
#   hardware_farm_id  — VARCHAR(50) PK used by the Arduino sketch
#                       e.g. "FARM-MARK-001". SensorReading and
#                       IrrigationLog FK to this field.
#   farmer_name       — human-readable node identity (Arduino FARM_ID)
#   farmer_phone      — contact info stored alongside the hardware node
#   is_active         — hardware schema flag (1 = active, 0 = inactive)
# ══════════════════════════════════════════════════════════════
class Farm(db.Model):
    __tablename__ = 'farms'

    id                    = db.Column(db.Integer, primary_key=True)
    owner_id              = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    name                  = db.Column(db.String(100), nullable=False)
    region                = db.Column(db.String(50), nullable=False)
    town                  = db.Column(db.String(100))
    crop_type             = db.Column(db.String(100), nullable=False)
    size_hectares         = db.Column(db.Numeric(6, 2))
    latitude              = db.Column(db.Numeric(9, 6))
    longitude             = db.Column(db.Numeric(9, 6))
    sensor_node_id        = db.Column(db.String(50), unique=True, index=True)
    # ── Hardware identity fields ──────────────────────────────
    hardware_farm_id      = db.Column(db.String(50), unique=True)   # e.g. "FARM-MARK-001"
    farmer_name           = db.Column(db.String(100))
    farmer_phone          = db.Column(db.String(20))
    # ── Quality & status ──────────────────────────────────────
    current_quality_score = db.Column(db.Integer, default=0, nullable=False)
    is_active             = db.Column(db.Integer, default=1, nullable=False)  # TINYINT(1)
    notes                 = db.Column(db.Text)
    created_at            = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at            = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    readings          = db.relationship('SensorReading', backref='farm', lazy='dynamic',
                                        cascade='all, delete-orphan',
                                        foreign_keys='SensorReading.farm_id')
    forecasts         = db.relationship('HarvestForecast', backref='farm', lazy='dynamic',
                                        cascade='all, delete-orphan')
    irrigation_events = db.relationship('IrrigationLog', backref='farm', lazy='dynamic',
                                        cascade='all, delete-orphan',
                                        foreign_keys='IrrigationLog.farm_id')

    def __repr__(self):
        return f'<Farm {self.name} [{self.hardware_farm_id}]>'


# ══════════════════════════════════════════════════════════════
# SENSOR READING  (hardware schema — Phase 5.3)
#
# Matches farmlink_phase5 hardware schema exactly:
#   reading_id      VARCHAR(30) PRIMARY KEY  (Arduino-generated)
#   farm_id         VARCHAR(50) FK → farms.hardware_farm_id
#   recorded_at     DATETIME    DS3231 RTC hardware clock
#   inserted_at     DATETIME    when row entered MySQL
#   temperature     DECIMAL(5,2)
#   humidity        DECIMAL(5,2)
#   soil_moisture   DECIMAL(5,1)  ← 1 decimal place (hardware precision)
#   is_raining      TINYINT(1)
#   rain_intensity  INT
#   heat_stress_flag   TINYINT(1)
#   irrigation_active  TINYINT(1)
#   quality_score   DECIMAL(5,2)  written by MySQL trigger
#   sync_status     ENUM('BUFFERED','LIVE','SYNCED')
#
# NOTE: light_intensity removed (not in hardware schema).
#       No integer surrogate PK — reading_id is the PK.
# ══════════════════════════════════════════════════════════════
class SensorReading(db.Model):
    __tablename__ = 'sensor_readings'

    # ── Primary key (Arduino-generated hardware ID) ───────────
    reading_id        = db.Column(db.String(30), primary_key=True)
    # ── Farm reference → hardware_farm_id ─────────────────────
    farm_id           = db.Column(db.String(50),
                                  db.ForeignKey('farms.hardware_farm_id', ondelete='CASCADE'),
                                  nullable=False, index=True)
    # ── Timestamps ────────────────────────────────────────────
    recorded_at       = db.Column(db.DateTime, nullable=False, index=True)
    inserted_at       = db.Column(db.DateTime, default=datetime.utcnow)
    # ── Core sensor values ────────────────────────────────────
    temperature       = db.Column(db.Numeric(5, 2))
    humidity          = db.Column(db.Numeric(5, 2))
    soil_moisture     = db.Column(db.Numeric(5, 1))   # DECIMAL(5,1) — hardware precision
    # ── Rain sensor ───────────────────────────────────────────
    is_raining        = db.Column(db.Integer, default=0, nullable=False)    # TINYINT(1)
    rain_intensity    = db.Column(db.Integer, default=0, nullable=False)
    # ── Automation flags ──────────────────────────────────────
    heat_stress_flag  = db.Column(db.Integer, default=0, nullable=False)    # TINYINT(1)
    irrigation_active = db.Column(db.Integer, default=0, nullable=False)    # TINYINT(1)
    # ── Quality score (written by MySQL trigger) ──────────────
    quality_score     = db.Column(db.Numeric(5, 2))
    # ── Sync status (hardware vocabulary only) ────────────────
    sync_status       = db.Column(
                            db.Enum('BUFFERED', 'LIVE', 'SYNCED'),
                            default='BUFFERED', nullable=False
                        )

    # ── One reading can produce multiple alerts ───────────────
    alerts = db.relationship('Alert', backref='reading', lazy='dynamic')

    def __repr__(self):
        return f'<Reading {self.reading_id} farm={self.farm_id} @ {self.recorded_at}>'


# ══════════════════════════════════════════════════════════════
# ALERT  (IoT hardware — Phase 5.6)
#
# One row per alert event detected by the Python bridge.
# Written automatically by the bridge — never directly by
# the website. The website only reads from this table
# (e.g. to display alert history on a farm dashboard).
#
# WHY THIS IS SEPARATE FROM SensorReading:
#   SensorReading already stores heat_stress_flag and
#   irrigation_active as simple 0/1 flags. But those flags
#   don't tell you WHEN an alert was raised, WHAT VALUE
#   triggered it, or give you a queryable alert history.
#   This table fills that gap — one row per alert event,
#   with the exact sensor value that crossed the threshold.
#
# alert_type values:
#   HEAT_STRESS        — temperature exceeded threshold
#   CRITICAL_DROUGHT   — soil moisture dropped below 20 %
#   IRRIGATION_TRIGGER — soil below 30 % and pump activated
#
# reading_id FK uses SET NULL on delete so that deleting
# a sensor reading does NOT wipe out the alert history.
# farm_id is stored directly (no FK constraint) so that
# alert history survives even if a farm record is edited.
# ══════════════════════════════════════════════════════════════
class Alert(db.Model):
    __tablename__ = 'alerts'

    alert_id     = db.Column(db.Integer, primary_key=True, autoincrement=True)

    # ── Which reading triggered this alert ───────────────────
    # SET NULL on delete: if the reading is deleted, the alert
    # row survives with reading_id = NULL (history is kept).
    reading_id   = db.Column(db.String(30),
                             db.ForeignKey('sensor_readings.reading_id',
                                           ondelete='SET NULL'),
                             nullable=True,
                             index=True)

    # ── Which farm this alert belongs to ─────────────────────
    # Stored as a plain string — no FK constraint — so alert
    # history is never accidentally deleted via cascade.
    # Matches farms.hardware_farm_id format e.g. "FARM-MARK-001"
    farm_id      = db.Column(db.String(50), nullable=True, index=True)

    # ── What kind of alert and what value triggered it ───────
    alert_type   = db.Column(db.String(50))         # HEAT_STRESS / CRITICAL_DROUGHT / IRRIGATION_TRIGGER
    alert_value  = db.Column(db.Numeric(8, 2))      # the exact sensor reading that crossed the line

    # ── When the bridge detected and logged this alert ───────
    triggered_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Alert {self.alert_type} val={self.alert_value} reading={self.reading_id}>'


# ══════════════════════════════════════════════════════════════
# IRRIGATION LOG  (hardware schema — Phase 5.3)
#
# Records each complete irrigation event triggered by the
# Arduino (AUTO) or manually via the web app (MANUAL).
# One row per irrigation event, not per sensor reading.
#
#   farm_id         VARCHAR(50) FK → farms.hardware_farm_id
#   trigger_moisture DECIMAL(5,1)  ← 1 decimal place (hardware)
# ══════════════════════════════════════════════════════════════
class IrrigationLog(db.Model):
    __tablename__ = 'irrigation_log'

    event_id         = db.Column(db.Integer, primary_key=True, autoincrement=True)
    farm_id          = db.Column(db.String(50),
                                 db.ForeignKey('farms.hardware_farm_id', ondelete='CASCADE'),
                                 nullable=False, index=True)
    started_at       = db.Column(db.DateTime, nullable=False, index=True)
    duration_seconds = db.Column(db.Integer)
    trigger_moisture = db.Column(db.Numeric(5, 1))   # DECIMAL(5,1) — hardware precision
    trigger_type     = db.Column(db.Enum('AUTO', 'MANUAL'), default='AUTO', nullable=False)
    notes            = db.Column(db.String(200))

    def __repr__(self):
        return f'<IrrigationLog farm={self.farm_id} @ {self.started_at} [{self.trigger_type}]>'


# ══════════════════════════════════════════════════════════════
# HARVEST FORECAST
# Generated automatically after 28+ days of sensor data.
# Buyers are alerted when a forecast is created.
# ══════════════════════════════════════════════════════════════
class HarvestForecast(db.Model):
    __tablename__ = 'harvest_forecasts'

    id                     = db.Column(db.Integer, primary_key=True)
    farm_id                = db.Column(db.Integer, db.ForeignKey('farms.id', ondelete='CASCADE'), nullable=False)
    predicted_harvest_start= db.Column(db.Date, nullable=False)
    predicted_harvest_end  = db.Column(db.Date, nullable=False)
    confidence_score       = db.Column(db.Numeric(5, 2), nullable=False)
    data_points_used       = db.Column(db.Integer, default=0)
    buyers_alerted         = db.Column(db.Integer, default=0)
    is_active              = db.Column(db.Boolean, default=True)
    created_at             = db.Column(db.DateTime, default=datetime.utcnow)

    listings = db.relationship('ProduceListing', backref='forecast', lazy='dynamic')

    def __repr__(self):
        return f'<Forecast farm={self.farm_id} [{self.predicted_harvest_start}–{self.predicted_harvest_end}]>'


# ══════════════════════════════════════════════════════════════
# PRODUCE LISTING
# Created by farmers. quality_score_at_listing is locked
# at creation time; quality_score_live updates with sensor data.
# ══════════════════════════════════════════════════════════════
class ProduceListing(db.Model):
    __tablename__ = 'produce_listings'

    id                      = db.Column(db.Integer, primary_key=True)
    farmer_id               = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    farm_id                 = db.Column(db.Integer, db.ForeignKey('farms.id', ondelete='CASCADE'), nullable=False)
    forecast_id             = db.Column(db.Integer, db.ForeignKey('harvest_forecasts.id', ondelete='SET NULL'), nullable=True)
    crop_type               = db.Column(db.String(100), nullable=False)
    quantity_kg             = db.Column(db.Numeric(8, 2), nullable=False)
    price_per_kg            = db.Column(db.Numeric(10, 2), nullable=False)
    min_order_kg            = db.Column(db.Numeric(8, 2))
    quality_score_at_listing= db.Column(db.Integer, default=0)
    quality_score_live      = db.Column(db.Integer, default=0)
    description             = db.Column(db.Text)
    photo_url               = db.Column(db.String(500))
    status                  = db.Column(db.Enum('draft', 'active', 'sold', 'delisted'), default='draft')
    inquiry_count           = db.Column(db.Integer, default=0)
    created_at              = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at              = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<Listing {self.crop_type} by farmer={self.farmer_id} [{self.status}]>'


# ══════════════════════════════════════════════════════════════
# TRANSACTION
# Records every completed deal between farmer and buyer.
# Used by TrustScoreEngine to compute farmer reliability.
# ══════════════════════════════════════════════════════════════
class Transaction(db.Model):
    __tablename__ = 'transactions'

    id                 = db.Column(db.Integer, primary_key=True)
    listing_id         = db.Column(db.Integer, db.ForeignKey('produce_listings.id', ondelete='RESTRICT'), nullable=False)
    farmer_id          = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    buyer_id           = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    quantity_kg        = db.Column(db.Numeric(8, 2), nullable=False)
    agreed_price_per_kg= db.Column(db.Numeric(10, 2), nullable=False)
    total_amount       = db.Column(db.Numeric(12, 2), nullable=False)
    status             = db.Column(db.Enum('pending', 'completed', 'cancelled', 'disputed'), default='pending')
    is_on_time         = db.Column(db.Boolean, nullable=True)
    notes              = db.Column(db.Text)
    created_at         = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at       = db.Column(db.DateTime, nullable=True)


# ══════════════════════════════════════════════════════════════
# RATING  — buyer rates a farmer after a transaction
# ══════════════════════════════════════════════════════════════
class Rating(db.Model):
    __tablename__ = 'ratings'

    id             = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey('transactions.id', ondelete='CASCADE'), nullable=False)
    farmer_id      = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    buyer_id       = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    score          = db.Column(db.Integer, nullable=False)   # 1–5
    comment        = db.Column(db.Text)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)


# ══════════════════════════════════════════════════════════════
# BUYER ALERT — standing crop alert registered by a buyer
# ══════════════════════════════════════════════════════════════
class BuyerAlert(db.Model):
    __tablename__ = 'buyer_alerts'

    id               = db.Column(db.Integer, primary_key=True)
    buyer_id         = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    produce_type     = db.Column(db.String(100), nullable=False)
    region           = db.Column(db.String(50), nullable=False)
    min_quality_score= db.Column(db.Integer, default=0)
    min_trust_score  = db.Column(db.Numeric(3, 2), default=0.00)
    min_quantity_kg  = db.Column(db.Numeric(8, 2), default=0)
    is_active        = db.Column(db.Boolean, default=True)
    triggered_count  = db.Column(db.Integer, default=0)
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)


# ══════════════════════════════════════════════════════════════
# NOTIFICATION — in-app, email, or SMS notification
# ══════════════════════════════════════════════════════════════
class Notification(db.Model):
    __tablename__ = 'notifications'

    id           = db.Column(db.Integer, primary_key=True)
    recipient_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    type         = db.Column(db.Enum(
                       'harvest_alert', 'sensor_offline', 'quality_change',
                       'account_verified', 'account_suspended', 'listing_published',
                       'transaction_completed', 'buyer_enquiry', 'system'
                   ), default='system')
    title        = db.Column(db.String(200), nullable=False)
    message      = db.Column(db.Text, nullable=False)
    forecast_id  = db.Column(db.Integer, db.ForeignKey('harvest_forecasts.id', ondelete='SET NULL'), nullable=True)
    listing_id   = db.Column(db.Integer, db.ForeignKey('produce_listings.id',  ondelete='SET NULL'), nullable=True)
    channel      = db.Column(db.Enum('web', 'email', 'sms'), default='web')
    is_read      = db.Column(db.Boolean, default=False)
    sent_at      = db.Column(db.DateTime, default=datetime.utcnow)


# ══════════════════════════════════════════════════════════════
# CONTACT REQUEST — any user sends a message to any other user
#
# OOP DESIGN NOTE:
#   This class is responsible for everything a contact request
#   knows and can decide about itself. Routes and templates
#   never compute message logic — they ask the object.
#
# context_type values:
#   'listing_enquiry'  — buyer messaging farmer about a listing
#   'farmer_profile'   — buyer messaging farmer about their profile
#   'farmer_to_farmer' — farmer messaging another farmer
#
# ENCAPSULATION:
#   can_reply()       — object decides if a user may reply
#   is_unread_for()   — object decides if message is unread
#   context_label     — object builds its own human-readable label
# ══════════════════════════════════════════════════════════════
class ContactRequest(db.Model):
    __tablename__ = 'contact_requests'

    id           = db.Column(db.Integer, primary_key=True)

    # ── Who is talking to whom ────────────────────────────────
    sender_id    = db.Column(
                       db.Integer,
                       db.ForeignKey('users.id', ondelete='CASCADE'),
                       nullable=False,
                       index=True
                   )
    recipient_id = db.Column(
                       db.Integer,
                       db.ForeignKey('users.id', ondelete='CASCADE'),
                       nullable=False,
                       index=True
                   )

    # ── What the message is about ─────────────────────────────
    context_type = db.Column(
                       db.Enum(
                           'listing_enquiry',
                           'farmer_profile',
                           'farmer_to_farmer'
                       ),
                       nullable=False,
                       default='listing_enquiry'
                   )
    listing_id   = db.Column(
                       db.Integer,
                       db.ForeignKey('produce_listings.id', ondelete='SET NULL'),
                       nullable=True   # only filled for listing_enquiry
                   )

    # ── The conversation ──────────────────────────────────────
    message       = db.Column(db.Text, nullable=False)
    reply_message = db.Column(db.Text, nullable=True)   # one reply allowed

    # ── Lifecycle state ───────────────────────────────────────
    status     = db.Column(
                     db.Enum('sent', 'read', 'replied'),
                     nullable=False,
                     default='sent'
                 )
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    read_at    = db.Column(db.DateTime, nullable=True)
    replied_at = db.Column(db.DateTime, nullable=True)

    # ── Relationships — give direct access to sender/recipient ─
    sender    = db.relationship('User', foreign_keys=[sender_id],
                                backref=db.backref('sent_enquiries', lazy='dynamic'))
    recipient = db.relationship('User', foreign_keys=[recipient_id],
                                backref=db.backref('received_enquiries', lazy='dynamic'))
    listing   = db.relationship('ProduceListing', foreign_keys=[listing_id],
                                backref=db.backref('enquiries', lazy='dynamic'))

    # ══════════════════════════════════════════════════════════
    # ENCAPSULATED BEHAVIOUR — the object decides, not the route
    # ══════════════════════════════════════════════════════════

    def can_reply(self, user):
        """
        Returns True only when:
          1. The given user IS the recipient of this message, AND
          2. The message has not already been replied to.
        """
        return (
            user is not None
            and self.recipient_id == user.id
            and self.status != 'replied'
        )

    def is_unread_for(self, user):
        """
        Returns True when the given user is the recipient
        and the message status is still 'sent' (never opened).
        Used by the sidebar badge counter.
        """
        return (
            user is not None
            and self.recipient_id == user.id
            and self.status == 'sent'
        )

    @property
    def context_label(self):
        """
        Returns a human-readable string describing what
        this message is about. Templates never build this string
        themselves — they ask the object for it.
        """
        labels = {
            'listing_enquiry':  'Listing enquiry',
            'farmer_profile':   'Profile message',
            'farmer_to_farmer': 'Farmer message',
        }
        return labels.get(self.context_type, 'Message')

    def __repr__(self):
        return (
            f'<ContactRequest '
            f'from=user:{self.sender_id} '
            f'to=user:{self.recipient_id} '
            f'[{self.context_type}] [{self.status}]>'
        )