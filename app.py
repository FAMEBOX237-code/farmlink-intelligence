from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_bcrypt import Bcrypt
from config import Config

db = SQLAlchemy()
login_manager = LoginManager()
bcrypt = Bcrypt()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    login_manager.init_app(app)
    bcrypt.init_app(app)

    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'

    from routes.public import public_bp
    from routes.auth import auth_bp
    app.register_blueprint(public_bp)
    app.register_blueprint(auth_bp)

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)