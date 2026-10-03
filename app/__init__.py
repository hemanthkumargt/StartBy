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
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
    app.config["TEMPLATES_AUTO_RELOAD"] = True

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

    from app.routes import auth, cron, health, pages, settings, tasks

    app.register_blueprint(health.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(tasks.bp)
    app.register_blueprint(settings.bp)
    app.register_blueprint(cron.bp)
    app.register_blueprint(pages.bp)

    # Cloud Scheduler calls this with a shared secret header, not a browser
    # session — it carries no CSRF token to check. X-Cron-Secret is its auth.
    csrf.exempt(cron.bp)

    return app
