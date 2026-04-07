from flask import Blueprint, render_template

public_bp = Blueprint('public', __name__)

@public_bp.route('/')
def landing():
    return '<h1>FarmLink — landing page coming soon</h1>'

@public_bp.route('/about')
def about():
    return render_template('public/about.html')

@public_bp.route('/how-it-works')
def how_it_works():
    return render_template('public/how_it_works.html')