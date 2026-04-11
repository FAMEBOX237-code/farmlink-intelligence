from flask import Blueprint, render_template, request, redirect, url_for

# Blueprint
auth_bp = Blueprint('auth', __name__)

# =========================
# LOGIN ROUTE
# =========================
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        print("LOGIN:", email, password)

        return "Login submitted"

    return render_template('login.html')


# =========================
# REGISTER ROUTE
# =========================
@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        firstname = request.form.get('firstname')
        lastname = request.form.get('lastname')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm = request.form.get('confirm')
        role = request.form.get('role')

        # ✅ Check passwords match
        if password != confirm:
            return "Passwords do not match"

        # 🧪 TEMP: show data in terminal
        print("REGISTER:", firstname, lastname, email, role)

        # 👉 redirect to login page after success
        return redirect(url_for('auth.login'))

    return render_template('register.html')