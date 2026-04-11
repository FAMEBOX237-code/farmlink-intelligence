from flask import Blueprint, render_template, request, redirect, url_for, flash, session
import pymysql
import uuid
import re
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_db_connection
from datetime import datetime, timedelta
from flask_login import login_required, current_user, login_user
from models import User
from flask_login import logout_user
from email_validator import validate_email, EmailNotValidError





auth = Blueprint('auth', __name__)

# ================= REGISTER =================
@auth.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        full_name = request.form.get('full_name')
        email = request.form.get('email')
        password = request.form.get('password')
        try:
            valid = validate_email(email)
            email = valid.email
        except      EmailNotValidError:
           flash("Invalid email address.", "danger")
           return redirect(url_for('auth.register'))
        
        password_pattern = r'^(?=.*[A-Za-z])(?=.*\d)(?=.*[@$!%*#?&]).{8,}$'

        if not re.match(password_pattern, password):
           flash("Password must be at least 8 characters and include letters, numbers, and special characters.", "danger")
           return redirect(url_for('auth.register'))
        phone = request.form.get('phone')
        role = request.form.get('role')
        region = request.form.get('region') if role == 'farmer' else None
        primary_crop = request.form.get('primary_crop') if role == 'farmer' else None

        password_hash = generate_password_hash(password)

        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                # Check if user exists
                cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
                if cursor.fetchone():
                    flash('This email is already registered.', 'danger')
                    return redirect(url_for('auth.register'))

                # Insert user
                cursor.execute("""
                    INSERT INTO users 
                    (full_name, email, password_hash, phone, role, region, primary_crop, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (full_name, email, password_hash, phone, role, region, primary_crop, datetime.now()))

                conn.commit()

            flash('Account created successfully!', 'success')
            return redirect(url_for('auth.login'))

        except Exception as e:
            print("ERROR:", e)
            flash('Error while creating account.', 'danger')

        finally:
            conn.close()

    return render_template('register.html')


@auth.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
                user = cursor.fetchone()

                if user and check_password_hash(user['password_hash'], password):
                    login_user(User(user))

                    flash(f'Welcome back, {user["full_name"]}!', 'success')

                    if user['role'] == 'farmer':
                        return redirect(url_for('auth.dashboard'))
                    elif user['role'] == 'buyer':
                        return redirect(url_for('buyer.marketplace'))
                    else:
                        return redirect(url_for('auth.dashboard'))

                else:
                    flash('Incorrect email or password.', 'danger')

        finally:
            conn.close()

    return render_template('login.html', lockout_seconds=lockout_seconds)


# ================= PASSWORD RESET =================

@auth.route('/reset-request', methods=['POST'])
def reset_request():
    email = request.form.get('email')

    if not email:
        flash('Please enter your email.', 'danger')
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, full_name FROM users WHERE email=%s", (email,))
            user = cursor.fetchone()

            if not user:
                # Security: Don't reveal if email exists or not
                flash('If an account with this email exists, a reset link has been sent.', 'success')
                return redirect(url_for('auth.login'))

            # Generate secure token
            token = str(uuid.uuid4())
            expiry = datetime.now() + timedelta(minutes=30)

            cursor.execute("""
                UPDATE users 
                SET reset_token=%s, reset_token_expiry=%s 
                WHERE id=%s
            """, (token, expiry, user['id']))
            conn.commit()

            # TODO: Later replace with real email sending (e.g. Flask-Mail)
            reset_link = url_for('auth.reset_password', token=token, _external=True)
            print(f"\n🔗 PASSWORD RESET LINK for {email}:")
            print(f"{reset_link}\n")
            print("Copy and paste this link in your browser to reset password.\n")

            flash('If an account with this email exists, a reset link has been sent.', 'success')

    except Exception as e:
        print("Reset request error:", e)
        flash('An error occurred. Please try again.', 'danger')
    finally:
        conn.close()

    return redirect(url_for('auth.login'))


@auth.route('/reset/<token>', methods=['GET', 'POST'])
def reset_password(token):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Validate token
            cursor.execute("""
                SELECT id, full_name, email 
                FROM users 
                WHERE reset_token=%s AND reset_token_expiry > %s
            """, (token, datetime.now()))
            user = cursor.fetchone()

            if not user:
                flash('This reset link is invalid or has expired.', 'danger')
                return redirect(url_for('auth.login'))

            if request.method == 'POST':
                password = request.form.get('password')
                confirm_password = request.form.get('confirm_password')

                if not password or password != confirm_password:
                    flash('Passwords do not match.', 'danger')
                    return render_template('reset_password.html', token=token, user=user)

                if len(password) < 6:
                    flash('Password must be at least 6 characters long.', 'danger')
                    return render_template('reset_password.html', token=token, user=user)

                hashed = generate_password_hash(password)

                cursor.execute("""
                    UPDATE users 
                    SET password_hash=%s, reset_token=NULL, reset_token_expiry=NULL
                    WHERE id=%s
                """, (hashed, user['id']))
                conn.commit()

                flash('Your password has been reset successfully!', 'success')
                return redirect(url_for('auth.login'))

            # GET request - show reset form
            return render_template('reset_password.html', token=token, user=user)

    finally:
        conn.close()

# ================= RESET PAGE =================
@auth.route('/reset-password')
def reset_password_page():
    return render_template('reset_password.html')



@auth.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html', user=current_user)


# ================= LOGOUT =================
@auth.route('/logout')
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))