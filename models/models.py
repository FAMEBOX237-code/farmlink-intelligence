from flask_login import UserMixin

class User(UserMixin):
    def __init__(self, user_data):
        self.id = user_data['id']
        self.full_name = user_data['full_name']
        self.email = user_data['email']
        self.role = user_data['role']