from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, render_template

from .extensions import db, login_manager, sock
from .models import User


def create_app() -> Flask:
    load_dotenv()

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object("app.config.Config")

    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    sock.init_app(app)

    login_manager.login_view = "auth.login"
    login_manager.login_message = "Войдите в систему, чтобы продолжить."
    login_manager.login_message_category = "warning"

    @login_manager.user_loader
    def load_user(user_id: str):
        return db.session.get(User, int(user_id))

    from .auth import auth_bp
    from .main import main_bp
    from .api import api_bp
    from .realtime import register_socket_routes

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp)
    register_socket_routes(sock)

    @app.errorhandler(403)
    def forbidden(_error):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("errors/404.html"), 404

    return app
