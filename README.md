# FarmLink Intelligence
**IoT-Verified Smart Agricultural Marketplace for Cameroonian Smallholder Farmers**

> A supply intelligence platform where objects behave, the database acts,  
> and hardware generates the trust that buyers need.

---

## What This Project Is

FarmLink Intelligence is a web-based, IoT-integrated smart agricultural marketplace built specifically for Cameroonian smallholder farmers. It is an integrated academic project covering three courses in one unified system:

| Course | Deliverable |
|--------|-------------|
| **IoT** | Physical sensor node (Arduino Uno + ESP8266) — reads soil, temperature, humidity, light, and rainfall every 30 minutes and transmits to the cloud |
| **OOAD** | 14-class object model with Observer, Strategy, and Template Method design patterns |
| **DBMS** | 14-table relational database in 3NF with 3 triggers, 3 stored procedures, and 2 views |

---

## The Three Intelligence Layers

### Core — IoT Quality Verification
Every produce listing carries a sensor-verified quality score computed from live farm data. Quality is **measured by hardware**, not typed by farmers.

### Approach A — Farmer Trust Scoring
Every farmer carries a dynamic reputation score built from transaction completion history, on-time delivery records, and buyer ratings. The `TrustScoreEngine` maintains this automatically.

### Approach B — Predictive Harvest Forecasting
When a farm accumulates 28+ days of sensor data, the system predicts the upcoming harvest window and automatically notifies registered buyers — before the farmer even posts a listing.

---

## Project Structure

```
farmlink-intelligence/
│
├── app.py                   # Application factory — creates and wires the Flask app
├── config.py                # All configuration — reads secrets from .env via os.getenv()
├── extensions.py            # Flask extension instances (db, bcrypt, login_manager, etc.)
│
├── models/
│   └── models.py            # All 10 SQLAlchemy ORM models (tables)
│
├── routes/
│   ├── auth.py              # /register  /login  /logout  /reset-password
│   ├── farmer.py            # /farmer/*  — farmer portal (dashboard, farms, listings, forecasts)
│   ├── buyer.py             # /marketplace  /listings/*  /buyer/*
│   ├── admin.py             # /admin/*  — admin panel
│   ├── public.py            # /  /about  /how-it-works  + global error handlers
│   └── api.py               # IoT sensor data ingestion endpoint (reserved)
│
├── services/
│   ├── quality_engine.py    # Computes sensor status + quality score display data
│   ├── trust_engine.py      # Computes farmer trust score breakdown
│   ├── forecast_engine.py   # Computes harvest forecast display context
│   └── alert_dispatcher.py  # Classifies notifications into display-ready dicts
│
├── templates/
│   ├── admin/               # Admin portal pages
│   ├── buyer/               # Buyer portal pages
│   ├── farmer/              # Farmer portal pages
│   ├── public/              # Landing, login, register, reset password, about
│   ├── partials/            # Shared sidebars and navbar
│   └── errors/              # 403, 404, 429, 500 error pages
│
├── static/
│   ├── css/                 # Per-portal stylesheets (admin, auth, buyer, farmer, public)
│   ├── js/                  # Client-side JavaScript
│   └── uploads/             # User-uploaded profile photos and listing images
│
├── scripts/
│   ├── create_tables.py     # One-time setup: creates all database tables
│   └── seed.py              # Creates admin account + optional test accounts
│
├── requirements.txt
├── .env                     # !! NEVER commit — contains real secrets
├── .env.example             # Safe template — commit this instead
└── .gitignore
```

> **Note on structure:** The project uses a flat layout where `app.py`, `config.py`, and `extensions.py` live at the root level alongside the `routes/`, `models/`, and `services/` packages. This differs from the original plan document which described an `app/` subfolder layout. The flat layout was chosen during development for simplicity and works identically.

---

## Database Models

| Model | Table | Purpose |
|-------|-------|---------|
| `User` | `users` | All accounts — farmer / buyer / admin |
| `Farm` | `farms` | Farms owned by farmers, linked to IoT nodes |
| `SensorReading` | `sensor_readings` | One row per 30-minute IoT reading |
| `HarvestForecast` | `harvest_forecasts` | Predicted harvest windows from sensor trends |
| `ProduceListing` | `produce_listings` | Marketplace listings with live quality scores |
| `Transaction` | `transactions` | Completed buyer-farmer deals |
| `Rating` | `ratings` | Buyer star ratings of farmers (1–5) |
| `BuyerAlert` | `buyer_alerts` | Standing alert criteria per buyer |
| `Notification` | `notifications` | In-app notifications (harvest alerts, system, etc.) |
| `ContactRequest` | `contact_requests` | Buyer enquiry messages to farmers via listings |

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Frontend | HTML5, CSS3, Vanilla JavaScript |
| Backend | Python 3.12, Flask 3.0 |
| ORM | Flask-SQLAlchemy 3.1 |
| Database | MySQL 8.0 (InnoDB, utf8mb4) |
| Auth | Flask-Login + Flask-Bcrypt |
| Forms | Flask-WTF (CSRF protection) |
| Email | Flask-Mail (password reset) |
| Rate Limiting | Flask-Limiter |
| IoT Bridge | Firebase Realtime Database → MySQL via Python bridge |
| Hardware | Arduino Uno, ESP8266, DHT22, Capacitive Soil Sensor, BH1750, DS3231 RTC, MicroSD, Relay + Pump, Solar Panel + Battery, OLED, Buzzer + LED |

---

## Local Setup

### 1. Clone and create your environment

```bash
git clone <your-repo-url>
cd farmlink-intelligence
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure your environment

```bash
cp .env.example .env
```

Open `.env` and fill in your values:

```env
SECRET_KEY=<generate with: python -c "import secrets; print(secrets.token_hex(32))">
DATABASE_URL=mysql+pymysql://YOUR_DB_USER:YOUR_DB_PASSWORD@localhost/farmlink
ADMIN_EMAIL=admin@farmlink.cm
ADMIN_PASSWORD=<choose a strong password>
```

### 3. Create the database tables

```bash
python scripts/create_tables.py
```

### 4. Seed the admin and test accounts

```bash
python scripts/seed.py
```

This creates:
- **Admin** — email and password from your `.env`
- **Test Farmer** — `farmer@farmlink.cm` / password from `.env`
- **Test Buyer** — `buyer@farmlink.cm` / password from `.env`

### 5. Run the app

```bash
python app.py
```

Visit: `http://localhost:5000`

---

## Security Notes

- Passwords are hashed with **bcrypt** — never stored in plain text
- All POST forms are protected with **CSRF tokens** (Flask-WTF)
- Login and registration endpoints are **rate-limited** (POST only — page visits are never counted)
- Sessions use `HttpOnly` cookies with `SameSite=Lax`
- Password reset uses **signed, time-limited tokens** via `itsdangerous` (30-minute expiry)
- The reset flow never reveals whether an email address exists in the system
- **Never commit `.env`** — it contains your `SECRET_KEY` and database password

---

## User Roles

| Role | Portal | Access |
|------|--------|--------|
| **Farmer** | `/farmer/*` | Dashboard, farms, listings, forecasts, trust score, notifications, profile |
| **Buyer** | `/marketplace`, `/buyer/*` | Browse listings, listing detail, pre-order alerts, notifications, profile |
| **Admin** | `/admin/*` | Platform dashboard, account management, sensor monitor, regional reports |

Public pages (no login required): landing, about, how it works, marketplace browse, listing detail, farmer public profile.

---

## Academic Context

**Institution:** The ICT University, Department of Computer Science  
**Programme:** Spring 2026  
**Courses covered:** IoT · Object-Oriented Analysis & Design · Database Management Systems