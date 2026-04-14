from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_bcrypt import Bcrypt
from config import Config

# ======================
# Extensions
# ======================
db = SQLAlchemy()
login_manager = LoginManager()
bcrypt = Bcrypt()


# ======================
# App Factory
# ======================
def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Init extensions
    db.init_app(app)
    login_manager.init_app(app)
    bcrypt.init_app(app)

    # Flask-Login settings
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'

    # ======================
    # IMPORT MODELS HERE
    # ======================
    from models import User

    # ======================
    # USER LOADER (FIXED)
    # ======================
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # ======================
    # BLUEPRINTS
    # ======================
    from routes.public import public_bp
    from routes.auth import auth_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(auth_bp)

    return app


# ======================
# RUN SERVER
# ======================
if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)