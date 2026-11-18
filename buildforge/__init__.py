"""BuildForge — one GUI for every toolchain on this machine."""

__version__ = "1.1.0"
APP_NAME = "BuildForge"

from . import pathfix

pathfix.apply()
