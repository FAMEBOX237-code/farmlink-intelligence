from flask import Blueprint, render_template

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/register')
def register():
    return '<h1>Register page coming soon</h1>'

@auth_bp.route('/login')
def login():
    return '<h1>Login page coming soon</h1>'