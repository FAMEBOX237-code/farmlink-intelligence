import os
from dotenv import load_dotenv
load_dotenv()

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'farmlink-dev-key-change-in-production')
    SQLALCHEMY_DATABASE_URI = os.getenv(
        'DATABASE_URL',
        'mysql+pymysql://root:yourpassword@localhost/farmlink'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False