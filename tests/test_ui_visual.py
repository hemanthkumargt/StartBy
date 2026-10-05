"""Regression coverage for the Cloud 6 visual system and motion safeguards."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "app" / "static"


def _read(relative_path):
    return (STATIC / relative_path).read_text()


def test_wordmark_never_receives_the_filled_logo_background():
    skin = _read("css/skin.css")
    dark = _read("css/dark.css")

    for source in (skin, dark):
        selector = ".brand-monogram__logo--wordmark"
        block_start = source.index(selector)
        block = source[block_start : source.index("}", block_start) + 1]
        assert "background: transparent" in block
        assert "box-shadow: none" in block


def test_revolving_edges_use_theme_specific_neon_palettes():
    skin = _read("css/skin.css")
    dark_start = skin.index('html[data-theme="dark"] .glass-edge')
    light_start = skin.index('html[data-theme="light"] .glass-edge')
    dark_block = skin[dark_start : skin.index("}", dark_start) + 1]
    light_block = skin[light_start : skin.index("}", light_start) + 1]

    assert "#5be7ff" in dark_block.lower()
    assert "#a879ff" in dark_block.lower()
    assert "f97316" in light_block or "orange" in light_block.lower()


def test_gsap_motion_does_not_compete_with_css_perspective_cards():
    effects = _read("js/effects.js")

    assert '".lp-slip"' not in effects.split("function animateFloatingComponents", 1)[1]
    assert '".lp-cta, .fab-mic"' in effects
    assert 'overwrite: "auto"' in effects
    assert "force3D: true" in effects
    assert "prefers-reduced-motion" in effects


def test_edge_rotation_is_continuous_and_reduced_motion_safe():
    effects = _read("js/effects.js")

    assert '"--edge-angle": "+=360"' in effects
    assert "ease: \"none\"" in effects
    assert "repeat: -1" in effects
    assert "if (reducedMotion || !window.gsap) return;" in effects
