from flask import Flask
from flask_wtf.csrf import generate_csrf

from app import db
from app.config import Config
from app.errors import register_error_handlers
from app.extensions import csrf, login_manager
from app.repositories import user_repo


def create_app(config: Config | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config or Config())

    csrf.init_app(app)
    login_manager.init_app(app)
    db.init_app(app)
    register_error_handlers(app)

    app.jinja_env.globals["csrf_token"] = generate_csrf

    @login_manager.user_loader
    def load_user(user_id: str):
        from app.models import User

        row = user_repo.find_by_id(db.get_db(), int(user_id))
        return User(row) if row is not None else None

    from app.routes import auth, health, pages

    app.register_blueprint(health.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(pages.bp)

    return app
