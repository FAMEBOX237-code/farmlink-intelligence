from flask import Blueprint, render_template

# Create Blueprint
farmer_bp = Blueprint('farmer', __name__, url_prefix='/farmer')


# -------------------------------
# NEW LISTING PAGE
# -------------------------------
@farmer_bp.route('/listings/new')
def new_listing():
    return render_template('farmer/listing_new.html')


# -------------------------------
# LISTING DETAIL PAGE (PUT BEFORE EDIT)
# -------------------------------
@farmer_bp.route('/listings/<int:id>/detail')
def listing_detail(id):
    listing = {
        "name": "Tomatoes",
        "quantity": "100 kg",
        "price": "500",
        "description": "Fresh organic tomatoes"
    }
    return render_template('farmer/listing_detail.html', listing=listing)


# -------------------------------
# EDIT LISTING PAGE
# -------------------------------
@farmer_bp.route('/listings/<int:id>')
def edit_listing(id):
    listing = {
        "name": "Tomatoes",
        "quantity": "100 kg",
        "price": "500",
        "description": "Fresh organic tomatoes"
    }
    return render_template('farmer/listing_edit.html', listing=listing)


# -------------------------------
# ALERTS PAGE
# -------------------------------
@farmer_bp.route('/alerts')
def alerts():
    return render_template('farmer/alerts.html')