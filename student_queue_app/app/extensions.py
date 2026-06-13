from flask_login import LoginManager
from flask_sock import Sock
from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()
login_manager = LoginManager()
sock = Sock()
