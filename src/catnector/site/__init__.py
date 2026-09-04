"""Catnector's site connection: the client half of the open protocol.

Specified in the `catnector-protocol` repository (`SPEC.md`, version 1),
which is normative. Catnector implements it rather than importing it — a
disagreement between the two is a finding, not a merge.
"""

from __future__ import annotations

from .client import Capabilities, Phase, SiteClient
from .messages import SessionInfo, explain_close, is_terminal
from .storage import SiteProfile, load_sites, save_sites
from .tokens import Token, TokenDamaged, TokenError, decode, encode, is_local

__all__ = [
    "Capabilities",
    "Phase",
    "SessionInfo",
    "SiteClient",
    "SiteProfile",
    "Token",
    "TokenDamaged",
    "TokenError",
    "decode",
    "encode",
    "explain_close",
    "is_local",
    "is_terminal",
    "load_sites",
    "save_sites",
]
