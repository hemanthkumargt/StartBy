"""Single source for the Phase 2 feature-flag shape. Both Jinja templates
(via app/__init__.py's context processor) and the service layer (via
routes, threaded through as one `flags` dict) read flags through this one
function — adding FEATURE_SMART_CAPTURE's or FEATURE_INSIGHTS' actual
behaviour later never means touching N call sites to add a new parameter,
only using the key that's already here."""


def read_feature_flags(config) -> dict:
    return {
        "estimates": config["FEATURE_ESTIMATES"],
        "smart_capture": config["FEATURE_SMART_CAPTURE"],
        "insights": config["FEATURE_INSIGHTS"],
        "voice": config["FEATURE_VOICE"],
    }
