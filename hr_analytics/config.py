"""Connection settings: Streamlit secrets first (cloud), then environment / .env (local)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:  # python-dotenv is optional
    pass


@dataclass(frozen=True)
class DBSettings:
    host: str = "127.0.0.1"
    port: int = 3306
    user: str = "root"
    password: str = ""
    pool_size: int = 5
    ssl: bool = False

    def __repr__(self) -> str:  # never print the password
        return f"DBSettings(host={self.host!r}, port={self.port}, user={self.user!r}, pool_size={self.pool_size})"


def _from_streamlit_secrets() -> dict | None:
    try:
        import streamlit as st

        if "mysql" in st.secrets:
            return dict(st.secrets["mysql"])
    except Exception:  # no secrets file, or not running under Streamlit
        return None
    return None


def load_settings() -> DBSettings:
    s = _from_streamlit_secrets()
    if s:
        return DBSettings(
            host=s.get("host", "127.0.0.1"),
            port=int(s.get("port", 3306)),
            user=s.get("user", "root"),
            password=s.get("password", ""),
            pool_size=int(s.get("pool_size", 5)),
            ssl=bool(s.get("ssl", False)),
        )
    return DBSettings(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", ""),
        pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
        ssl=os.getenv("DB_SSL", "false").lower() == "true",
    )
