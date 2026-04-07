import os
from dotenv import load_dotenv
load_dotenv() # This reads your .env file

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'fallback-key')
    SQLALCHEMY_DATABASE_URI = os.getenv(
        'DATABASE_URL',
        'mysql+pymysql://root:farmlink123@localhost/farmlink'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False