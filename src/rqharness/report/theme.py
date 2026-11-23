"""Org theming: an accent colour as CSS custom properties, and an inline logo. Nothing else is themeable."""

from __future__ import annotations

import html
import re

from rqharness.orgprofile import OrgProfile

_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
_LOGO = re.compile(r"^data:image/(png|jpeg|svg\+xml);base64,[A-Za-z0-9+/=]+$")
_ON_DARK_MIX = 0.35  # how far the text accent moves towards white on the dark background


def _channels(accent: str) -> tuple[int, int, int]:
    return int(accent[1:3], 16), int(accent[3:5], 16), int(accent[5:7], 16)


def _luminance(channels: tuple[int, int, int]) -> float:
    def lin(v: int) -> float:
        s = v / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(v) for v in channels)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def theme_css(profile: OrgProfile) -> str:
    """Custom-property overrides for the org accent in both colour schemes; "" without a valid accent."""
    accent = profile.theme.accent
    if not isinstance(accent, str) or not _HEX.match(accent):
        return ""
    accent = accent.upper()
    channels = _channels(accent)
    on_accent = "#FFFFFF" if _luminance(channels) < 0.4 else "#121212"
    lifted = "#" + "".join(f"{round(v + (255 - v) * _ON_DARK_MIX):02X}" for v in channels)
    # --v1 is the first non-baseline variant's curve, drawn in the signal colour in both palettes
    return (f":root{{--sig:{accent};--sigtxt:{accent};--on-sig:{on_accent};--v1:{accent}}}\n"
            f"@media (prefers-color-scheme:dark){{:root{{--sigtxt:{lifted};--v1:{accent}}}}}")


def logo_html(profile: OrgProfile) -> str:
    """The masthead logo as an inline data-URI image, or "" unless the URI is a plain base64 image."""
    uri = profile.theme.logo_data_uri
    if not isinstance(uri, str) or not _LOGO.match(uri):
        return ""
    name = profile.display_name or "Organisation"
    return f'<img class="logo" alt="{html.escape(str(name), quote=True)} logo" src="{html.escape(uri, quote=True)}">'
