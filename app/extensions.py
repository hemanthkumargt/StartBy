from urllib.parse import urlencode

from flask import jsonify, redirect, request, url_for
from flask_login import LoginManager
from flask_wtf import CSRFProtect

login_manager = LoginManager()
login_manager.login_view = "pages.login_page"


@login_manager.unauthorized_handler
def _unauthorized():
    """An expired/missing session on an /api/* route must return the app's
    documented JSON error shape, not Flask-Login's default HTML redirect —
    fetch() follows redirects, so the JSON API would otherwise hand back a
    200 OK with a login page's HTML body, which callers can't distinguish
    from success. Page routes keep the normal login-page redirect."""
    if request.path.startswith("/api/"):
        return jsonify({"error": {"code": "unauthorized", "message": "Login required"}}), 401
    query = urlencode({"next": request.url})
    return redirect(f"{url_for('pages.login_page')}?{query}")


csrf = CSRFProtect()
