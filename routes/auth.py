# ============================================================
# routes/auth.py — FarmLink Intelligence
#
# Authentication routes — fully working with database.
#
# ROUTES:
#   GET/POST /register       — create account
#   GET/POST /login          — sign in
#   GET      /logout         — sign out
#   GET/POST /reset-password — request + confirm password reset
#
# SECURITY MEASURES:
#   1. Passwords hashed with bcrypt (never stored plain text)
#   2. CSRF tokens on every POST form (Flask-WTF)
#   3. Rate limiting on POST only — page visits never count
#   4. Failed login tracking per IP (separate from page views)
#   5. Password reset uses signed time-limited tokens
#   6. Reset link never reveals if an email exists
#   7. Suspended accounts cannot log in
#   8. Authenticated users redirected away from login/register
#
# RATE LIMIT DESIGN:
#   Limits apply to methods=['POST'] only.
#   This means:
#     - Visiting /login 100 times: allowed (just viewing the page)
#     - Submitting the login form 5 times wrong: blocked for 15 min
#     - Submitting register 10 times in an hour: blocked
#   This is the correct behaviour. Page views must never be limited.
# ============================================================

import re

from flask import (
    Blueprint, render_template, request,
    redirect, url_for, flash, current_app
)
from flask_login import login_user, logout_user, login_required, current_user
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from flask_mail import Message

from extensions import db, bcrypt, limiter, mail
from models.models import User


auth_bp = Blueprint('auth', __name__, url_prefix='')


# ── Email validation ──────────────────────────────────────────
# Enforces real RFC-compliant email structure:
#   • Local part must start with a letter or digit
#   • Domain labels must start AND end with a letter or digit
#     (no leading/trailing hyphens — rejects "-1.com", "-domain.com")
#   • TLD must be letters only, at least 2 characters (no ".1", ".-")
#   • Max total length of 254 characters (SMTP standard)
#
# Examples that now correctly FAIL:
#   mark-1@-1.com     ← domain label starts with hyphen
#   user@@domain.com  ← double @
#   user@domain.c     ← TLD too short
#   user@.domain.com  ← domain starts with dot
#
# Examples that correctly PASS:
#   user@gmail.com
#   first.last+tag@mail.example.co.uk
#   farmer_1@agri-domain.org
_EMAIL_RE = re.compile(
    r'^[a-zA-Z0-9][a-zA-Z0-9._%+\-]{0,62}'   # local part: starts with alphanum
    r'@'
    r'(?:[a-zA-Z0-9]'                           # each domain label: starts with alphanum
    r'(?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?'     # label body (no trailing hyphen)
    r'\.)+'                                      # dot separating labels
    r'[a-zA-Z]{2,}$'                             # TLD: letters only, 2+ chars
)

def is_valid_email(email: str) -> bool:
    """Return True only if email passes structural validation."""
    return bool(email) and len(email) <= 254 and bool(_EMAIL_RE.match(email))


# ── Role-based redirect ───────────────────────────────────────
def redirect_by_role(user):
    """Send the logged-in user to their correct portal."""
    if user.role == 'farmer':
        return redirect(url_for('farmer.dashboard'))
    elif user.role == 'admin':
        return redirect(url_for('admin.dashboard'))
    else:
        return redirect(url_for('buyer.marketplace'))


# ── Password reset token helpers ──────────────────────────────
def generate_reset_token(email):
    """
    Create a signed, time-limited token encoding the email.
    Uses itsdangerous — the token is cryptographically signed
    with the app's SECRET_KEY. It cannot be forged.
    Expires after PASSWORD_RESET_EXPIRY seconds (30 minutes).
    """
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    return s.dumps(email, salt='farmlink-password-reset')


def verify_reset_token(token):
    """
    Decode and validate a reset token.
    Returns the email string on success.
    Returns None if the token is invalid or expired.
    """
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    expiry = current_app.config.get('PASSWORD_RESET_EXPIRY', 1800)
    try:
        email = s.loads(token, salt='farmlink-password-reset', max_age=expiry)
        return email
    except (SignatureExpired, BadSignature):
        return None


def send_reset_email(user_email, reset_url):
    """
    Send the password reset email.

    In development (MAIL_SUPPRESS_SEND=true in your .env):
      No email is sent. The reset link is printed to the
      terminal window where Flask is running. Copy it from
      there and paste it into your browser to test.

    In production (MAIL_SUPPRESS_SEND=false):
      A real email is sent via your configured SMTP server.
    """
    subject = 'Reset your FarmLink Intelligence password'
    body = (
        f'Hello,\n\n'
        f'You requested a password reset for your FarmLink Intelligence account.\n\n'
        f'Click the link below to set a new password.\n'
        f'This link expires in 30 minutes.\n\n'
        f'{reset_url}\n\n'
        f'If you did not request this, ignore this email — '
        f'your password will not change.\n\n'
        f'— The FarmLink Intelligence team\n'
        f'The ICT University, Cameroon'
    )

    if current_app.config.get('MAIL_SUPPRESS_SEND', True):
        # ── Development mode ─────────────────────────────────
        # Print the link to the terminal instead of sending email.
        # Look for this output in the terminal running Flask.
        print('\n' + '='*60)
        print('[DEV MODE] Password reset link — copy this into your browser:')
        print(reset_url)
        print('='*60 + '\n')
        current_app.logger.info(f'[DEV] Reset link for {user_email}: {reset_url}')
        return

    # ── Production mode ───────────────────────────────────────
    msg = Message(
        subject    = subject,
        recipients = [user_email],
        body       = body,
        sender     = current_app.config['MAIL_DEFAULT_SENDER'],
    )
    try:
        mail.send(msg)
    except Exception as e:
        current_app.logger.error(f'Failed to send reset email to {user_email}: {e}')


# ══════════════════════════════════════════════════════════════
# REGISTER  —  GET/POST /register
# ══════════════════════════════════════════════════════════════
@auth_bp.route('/register', methods=['GET', 'POST'])
@limiter.limit(
    '10 per hour',
    methods=['POST'],        # ← CRITICAL: only POST counts
    error_message='Too many registration attempts. Please wait before trying again.'
)
def register():
    """
    GET:  Show the registration form. No rate limiting applies.
    POST: Validate → check email uniqueness → hash password →
          write to database → redirect to login.
    """
    if current_user.is_authenticated:
        return redirect_by_role(current_user)

    preselected_role = request.args.get('role', '')

    if request.method == 'POST':
        # ── Read form fields ──────────────────────────────────
        first_name       = request.form.get('first_name', '').strip()
        last_name        = request.form.get('last_name',  '').strip()
        email            = request.form.get('email',      '').strip().lower()
        phone            = request.form.get('phone',      '').strip()
        password         = request.form.get('password',   '')
        confirm_password = request.form.get('confirm_password', '')
        role             = request.form.get('role',       '').strip()
        region           = request.form.get('region',     '').strip()
        primary_crop     = request.form.get('primary_crop','').strip()
        terms            = request.form.get('terms')

        # ── Validate — collect all errors before responding ───
        errors = []

        if not first_name or not last_name:
            errors.append('Please enter your first and last name.')

        if not is_valid_email(email):
            errors.append('Please enter a valid email address (e.g. name@domain.com).')

        if role not in ('farmer', 'buyer'):
            errors.append('Please select your role — Farmer or Buyer.')

        if len(password) < 8:
            errors.append('Password must be at least 8 characters long.')

        if password != confirm_password:
            errors.append('Passwords do not match. Please re-enter both.')

        if not terms:
            errors.append('You must agree to the Terms of Service to register.')

        if role == 'farmer' and not region:
            errors.append('Farmers must select their Cameroon region.')

        # ── Email uniqueness check ────────────────────────────
        if email and not errors:
            existing = User.query.filter_by(email=email).first()
            if existing:
                errors.append(
                    'An account with this email already exists. '
                    'Try logging in instead.'
                )

        # ── Show errors and re-render form ────────────────────
        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template(
                'public/register.html',
                preselected_role=role or preselected_role
            )

        # ── All valid — create the account ────────────────────
        password_hash = bcrypt.generate_password_hash(password).decode('utf-8')
        new_user = User(
            full_name     = f'{first_name} {last_name}',
            email         = email,
            phone         = phone or None,
            password_hash = password_hash,
            role          = role,
            region        = region or None,
            primary_crop  = primary_crop or None,
            is_verified   = False,
            is_suspended  = False,
        )
        db.session.add(new_user)
        db.session.commit()

        current_app.logger.info(f'New account registered: {email} [{role}]')
        # Do NOT flash a success message here.
        # login.html already has a static success box (#fb-success) that
        # the JS reveals when it detects ?registered=1 in the URL.
        # Flashing AND using ?registered=1 causes two success messages
        # to appear simultaneously — one from Flask's session, one from JS.
        return redirect(url_for('auth.login') + '?registered=1')

    return render_template(
        'public/register.html',
        preselected_role=preselected_role
    )


# ══════════════════════════════════════════════════════════════
# LOGIN  —  GET/POST /login
# ══════════════════════════════════════════════════════════════
@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit(
    '5 per 15 minutes',
    methods=['POST'],        # ← only form submissions count
    error_message='Too many failed login attempts. Please wait 15 minutes before trying again.'
)
def login():
    """
    GET:  Show the login form. No rate limiting — page visits are free.
    POST: Look up user → verify password → check not suspended →
          login_user() → redirect to portal.

    The 5-per-15-minutes limit means:
      - Visiting the login page 100 times: always allowed
      - Submitting wrong credentials 5 times: locked for 15 minutes
      This protects against brute-force password attacks.

    Security note: The error message on failure is always generic
    ("Incorrect email or password") — it never says which field
    is wrong. This prevents account enumeration attacks.
    """
    if current_user.is_authenticated:
        return redirect_by_role(current_user)

    if request.method == 'POST':
        email    = request.form.get('email',    '').strip().lower()
        password = request.form.get('password', '')

        user = User.query.filter_by(email=email).first()

        if user and bcrypt.check_password_hash(user.password_hash, password):
            # ── Password correct ──────────────────────────────
            if user.is_suspended:
                flash(
                    'Your account has been suspended. '
                    'Please contact the FarmLink team for assistance.',
                    'error'
                )
                return render_template('public/login.html')

            login_user(user, remember=True)
            current_app.logger.info(f'Login: {email} [{user.role}]')

            # Honour Flask-Login's "next" redirect
            next_page = request.args.get('next')
            if next_page and next_page.startswith('/'):
                return redirect(next_page)

            return redirect_by_role(user)

        else:
            # ── Wrong email or password ───────────────────────
            # Generic message — never reveal which field is wrong
            flash('Incorrect email or password. Please try again.', 'error')
            return render_template('public/login.html')

    return render_template('public/login.html')


# ══════════════════════════════════════════════════════════════
# LOGOUT  —  GET /logout
# ══════════════════════════════════════════════════════════════
@auth_bp.route('/logout')
@login_required
def logout():
    """Clear the session and return to the landing page."""
    current_app.logger.info(f'Logout: {current_user.email}')
    logout_user()
    # No flash message on logout — the user chose to leave,
    # and landing on the homepage already confirms they are out.
    # Showing a "you have been logged out" message is noise,
    # not information. Remove it for a clean, professional flow.
    return redirect(url_for('public.landing'))


# ══════════════════════════════════════════════════════════════
# RESET PASSWORD  —  GET/POST /reset-password
# ══════════════════════════════════════════════════════════════
@auth_bp.route('/reset-password', methods=['GET', 'POST'])
@limiter.limit(
    '5 per hour',
    methods=['POST'],        # ← only form submissions count
    error_message='Too many password reset requests. Please wait an hour before trying again.'
)
def reset_password():
    """
    Three stages, one route.

    STAGE 1 — Request link (POST, no token):
      Email submitted → generate signed token → send email (or
      print to terminal in dev mode) → redirect to Stage 2.

    STAGE 2 — Email sent screen (GET ?sent=1):
      Shows "check your email" message. JavaScript handles which
      panel is visible.

    STAGE 3 — Set new password (POST with token in form):
      Verify token → validate new password → hash it → save →
      log user in → redirect to portal.

    ABOUT EMAIL IN DEVELOPMENT:
      With MAIL_SUPPRESS_SEND=true (default), no real email is
      sent. The reset link is printed to the Flask terminal.
      Copy it from there and paste it into your browser to test.
    """
    if current_user.is_authenticated:
        return redirect_by_role(current_user)

    token = request.args.get('token') or request.form.get('token')

    if request.method == 'POST':

        # ── Stage 3: Token present → set new password ─────────
        if token:
            email = verify_reset_token(token)

            if not email:
                flash(
                    'This reset link has expired or is invalid. '
                    'Please request a new one.',
                    'error'
                )
                return redirect(url_for('auth.reset_password'))

            new_password     = request.form.get('new_password', '')
            confirm_password = request.form.get('confirm_new_password', '')

            errors = []
            if len(new_password) < 8:
                errors.append('Password must be at least 8 characters long.')
            if new_password != confirm_password:
                errors.append('Passwords do not match.')

            if errors:
                for error in errors:
                    flash(error, 'error')
                return render_template('public/reset_password.html', token=token)

            user = User.query.filter_by(email=email).first()
            if not user:
                flash('Account not found. Please register.', 'error')
                return redirect(url_for('auth.register'))

            user.password_hash = bcrypt.generate_password_hash(new_password).decode('utf-8')
            db.session.commit()

            # Do NOT auto-login after password reset.
            # Redirect to the login page with a single success message.
            # The user must log in consciously with their new password.
            # This is the professional standard — it confirms the new
            # password actually works and avoids session confusion.
            current_app.logger.info(f'Password reset completed: {email}')
            flash(
                'Your password has been updated successfully. '                'Please log in with your new password.',
                'success'
            )
            return redirect(url_for('auth.login'))

        # ── Stage 1: No token → request reset link ─────────────
        else:
            email = request.form.get('email', '').strip().lower()

            if not is_valid_email(email):
                flash('Please enter a valid email address (e.g. name@domain.com).', 'error')
                return render_template('public/reset_password.html')

            user = User.query.filter_by(email=email).first()
            if user:
                token     = generate_reset_token(email)
                reset_url = url_for('auth.reset_password', token=token, _external=True)
                send_reset_email(email, reset_url)

            # Always redirect — never reveal if email exists
            return redirect(
                url_for('auth.reset_password') + f'?sent=1&email={email}'
            )

    return render_template('public/reset_password.html', token=token)