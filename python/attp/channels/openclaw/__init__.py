"""ATTP channel adapter for the openclaw gateway.

Mirrors attp/channels/nanobot.py but targets the openclaw host: a thin Python
adapter is spawned by an openclaw Node channel plugin and bridged over HTTP.
See docs/attp-openclaw.md.
"""
from attp.channels.openclaw.adapter import OpenclawATTPAdapter

__all__ = ["OpenclawATTPAdapter"]
