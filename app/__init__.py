from flask import Flask, request
from flask_wtf.csrf import generate_csrf

from app import db, logging_setup
from app.config import Config
from app.errors import register_error_handlers
from app.extensions import csrf, login_manager
from app.feature_flags import read_feature_flags
from app.ratelimit import RateLimiter
from app.repositories import user_repo
from app.services import hooks
from app.services.calendar_service import CalendarSync
from app.services.integrations import CloudIntegrations


def create_app(config: Config | None = None) -> Flask:
    app = Flask(__name__)
    config = config or Config()
    config.validate_for_production()
    app.config.from_object(config)
    logging_setup.configure(app.config["LOG_FORMAT"])
    # Hard ceiling on any request body (smart capture's 5 MB PDF + overhead).
    app.config["MAX_CONTENT_LENGTH"] = 6 * 1024 * 1024
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=app.config["SECURE_COOKIES"],
        REMEMBER_COOKIE_HTTPONLY=True,
        REMEMBER_COOKIE_SAMESITE="Lax",
        REMEMBER_COOKIE_SECURE=app.config["SECURE_COOKIES"],
    )
    if app.config["BEHIND_PROXY"]:
        # nginx is the only thing that can reach gunicorn, so trust exactly one
        # hop of X-Forwarded-*: the real client IP (rate limits) and scheme.
        from werkzeug.middleware.proxy_fix import ProxyFix

        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
    # Per-app (not module-global) so every app instance, e.g. in tests, starts
    # with empty counters. Brute-force guard for the unauthenticated auth routes.
    app.extensions["auth_limiters"] = {
        # Only FAILED logins count, keyed by (client, email): one person's typos
        # or one attacker can't lock other people (or the real owner of that
        # account, who is on a different IP) out. The per-IP failure cap catches
        # guessing spread across many emails. Successful logins are never counted.
        # Sized for a hall of people sharing one network address (a demo day):
        # 20 wrong guesses per account and 150 in total per address per 5 minutes.
        "login_pair": RateLimiter(20, 300),
        "login_ip": RateLimiter(150, 300),
        # Generous: a hall full of people behind one NAT must all be able to sign up.
        "register": RateLimiter(30, 60),
    }
    # Per-user (not per-IP) write/cost guards for the signed-in API. Generous: a
    # normal person never meets them; a runaway script or a stuck client loop does.
    app.extensions["api_limiters"] = {
        "task_create": RateLimiter(120, 60),
        "voice_ask": RateLimiter(30, 60),
    }
    if app.config["ENV_NAME"] == "production" and not app.config["BEHIND_PROXY"]:
        app.logger.warning(
            "BEHIND_PROXY is 0 in production: every request will look like it comes "
            "from the proxy's address, so per-client rate limits act on the whole site."
        )
    app.config["TEMPLATES_AUTO_RELOAD"] = True

    csrf.init_app(app)
    login_manager.init_app(app)
    db.init_app(app)
    register_error_handlers(app)

    app.jinja_env.globals["csrf_token"] = generate_csrf

    @app.after_request
    def set_security_headers(response):
        # No CSP yet: the templates still carry inline <style>/<script> blocks,
        # so a strict policy would break pages; these cover framing and sniffing.
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        # Pages and API answers are per-user: never let a browser, proxy or the
        # back button keep one after sign-out. Static assets, the service worker
        # and the manifest have their own caching rules.
        if not (
            request.path.startswith("/static/")
            or request.path in ("/sw.js", "/manifest.webmanifest")
        ):
            response.headers.setdefault("Cache-Control", "no-store")
        if app.config["SECURE_COOKIES"]:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response

    @app.context_processor
    def inject_feature_flags():
        # Same shape and same reader the service layer uses (app/routes read
        # it as `flags` for task_service) — one place defines what a feature
        # flag set looks like.
        return {
            "feature_flags": read_feature_flags(app.config),
            "demo_social_login": app.config["ALLOW_DEMO_SOCIAL_LOGIN"],
            "demo_login_hint": app.config["DEMO_LOGIN_HINT"],
        }

    # One listener per app instance: Google Cloud side effects of task events
    # (Pub/Sub, BigQuery, Cloud Tasks). A no-op for anything left unconfigured.
    integrations = CloudIntegrations(app.config)
    app.extensions["integrations"] = integrations
    hooks.clear()
    hooks.register(integrations)
    calendar_sync = CalendarSync(app.config)
    app.extensions["calendar_sync"] = calendar_sync
    hooks.register(calendar_sync)

    @login_manager.user_loader
    def load_user(user_id: str):
        from app.models import User

        row = user_repo.find_by_id(db.get_db(), int(user_id))
        return User(row) if row is not None else None

    from app.routes import (
        auth,
        capture,
        cron,
        health,
        insights,
        pages,
        settings,
        tasks,
        voice,
        voice_notes,
    )
    from app.routes import calendar as calendar_routes

    app.register_blueprint(health.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(tasks.bp)
    app.register_blueprint(capture.bp)
    app.register_blueprint(insights.bp)
    app.register_blueprint(voice.bp)
    app.register_blueprint(voice_notes.bp)
    app.register_blueprint(calendar_routes.bp)
    app.register_blueprint(settings.bp)
    app.register_blueprint(cron.bp)
    app.register_blueprint(cron.internal_bp)
    app.register_blueprint(pages.bp)

    # Cloud Scheduler calls this with a shared secret header, not a browser
    # session — it carries no CSRF token to check. X-Cron-Secret is its auth.
    csrf.exempt(cron.bp)
    csrf.exempt(cron.internal_bp)

    return app
