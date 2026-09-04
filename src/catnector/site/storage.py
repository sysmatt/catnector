"""Registered site connections, stored in `sites.ini`.

Several sites can be registered at once — a HamQSY token and some other
site's token, both saved — but only one is active at a time. Rig profiles are
chosen independently: the two are orthogonal (docs/PLANNING.md §3.3).

This file holds credentials, so it is created readable only by its owner
(§4.2). That it is plain text is deliberate: a keyring would destroy the
portability the whole config design is buying.
"""

from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path

from ..paths import restrict_permissions
from .tokens import Token, TokenError, decode


@dataclass
class SiteProfile:
    """One registered site."""

    name: str
    token: str

    def decoded(self) -> Token:
        """Raises TokenError if the stored token is not usable."""
        return decode(self.token)

    @property
    def host(self) -> str:
        try:
            return self.decoded().host
        except TokenError:
            return "(unreadable token)"


def load_sites(path: Path) -> list[SiteProfile]:
    """Read registered sites. A missing or broken file yields none."""
    parser = configparser.ConfigParser()
    try:
        parser.read(path, encoding="utf-8")
    except (OSError, configparser.Error):
        return []
    sites = []
    for name in parser.sections():
        token = parser[name].get("token", "").strip()
        if token:
            sites.append(SiteProfile(name=name, token=token))
    return sites


def save_sites(path: Path, sites: list[SiteProfile]) -> None:
    """Write registered sites, then restrict the file's permissions."""
    parser = configparser.ConfigParser()
    for site in sites:
        parser[site.name] = {"token": site.token}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write("# catnector site connections.\n")
        handle.write("# THIS FILE CONTAINS CREDENTIALS - a token is a password.\n\n")
        parser.write(handle)
    restrict_permissions(path)
