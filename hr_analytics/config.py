
"""MySQL database configuration.

Priority:
1. Streamlit secrets (deployed application)
2. Local .env / environment variables
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


# Load .env for local development.
try:
    from dotenv import load_dotenv

    PROJECT_ROOT = Path(__file__).resolve().parents[1]
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass


@dataclass(frozen=True)
class DBSettings:
    host: str
    port: int
    user: str
    password: str
    pool_size: int = 5
    ssl: bool = False

    def __repr__(self) -> str:
        # Never expose the database password.
        return (
            f"DBSettings(host={self.host!r}, "
            f"port={self.port}, "
            f"user={self.user!r}, "
            f"pool_size={self.pool_size}, "
            f"ssl={self.ssl})"
        )


def _parse_bool(value) -> bool:
    if isinstance(value, bool):
        return value

    return str(value).strip().lower() in {
        "true", "1", "yes", "on"
    }


def _from_streamlit_secrets() -> dict | None:
    """Read database credentials from Streamlit Cloud secrets."""

    try:
        import streamlit as st

        if "mysql" in st.secrets:
            return dict(st.secrets["mysql"])

    except Exception:
        # No secrets configured, or running outside Streamlit.
        return None

    return None


def load_settings() -> DBSettings:
    """Load database settings from Streamlit secrets or .env."""

    secrets = _from_streamlit_secrets()

    if secrets is not None:
        host = secrets.get("host", "127.0.0.1")
        port = secrets.get("port", 3306)
        user = secrets.get("user", "hr_app")
        password = secrets.get("password", "")
        pool_size = secrets.get("pool_size", 5)
        ssl = secrets.get("ssl", False)

    else:
        host = os.getenv("DB_HOST", "127.0.0.1")
        port = os.getenv("DB_PORT", "3306")
        user = os.getenv("DB_USER", "hr_app")
        password = os.getenv("DB_PASSWORD", "")
        pool_size = os.getenv("DB_POOL_SIZE", "5")
        ssl = os.getenv("DB_SSL", "false")

    if not password:
        raise RuntimeError(
            "MySQL password is missing. Configure DB_PASSWORD "
            "in .env or [mysql].password in Streamlit secrets."
        )

    return DBSettings(
        host=str(host),
        port=int(port),
        user=str(user),
        password=str(password),
        pool_size=int(pool_size),
        ssl=_parse_bool(ssl),
    )



# """Connection settings: Streamlit secrets first (cloud), then environment / .env (local)."""
# from __future__ import annotations

# import os
# from dataclasses import dataclass
# from pathlib import Path

# try:
#     from dotenv import load_dotenv

#     load_dotenv(Path(__file__).resolve().parents[1] / ".env")
# except ImportError:  # python-dotenv is optional
#     pass


# @dataclass(frozen=True)
# class DBSettings:
#     host: str = "127.0.0.1"
#     port: int = 3306
#     user: str = "root"
#     password: str = ""
#     pool_size: int = 5
#     ssl: bool = False

#     def __repr__(self) -> str:  # never print the password
#         return f"DBSettings(host={self.host!r}, port={self.port}, user={self.user!r}, pool_size={self.pool_size})"


# def _from_streamlit_secrets() -> dict | None:
#     try:
#         import streamlit as st

#         if "mysql" in st.secrets:
#             return dict(st.secrets["mysql"])
#     except Exception:  # no secrets file, or not running under Streamlit
#         return None
#     return None


# def load_settings() -> DBSettings:
#     s = _from_streamlit_secrets()
#     if s:
#         return DBSettings(
#             host=s.get("host", "127.0.0.1"),
#             port=int(s.get("port", 3306)),
#             user=s.get("user", "root"),
#             password=s.get("password", ""),
#             pool_size=int(s.get("pool_size", 5)),
#             ssl=bool(s.get("ssl", False)),
#         )
#     return DBSettings(
#         host=os.getenv("DB_HOST", "127.0.0.1"),
#         port=int(os.getenv("DB_PORT", "3306")),
#         user=os.getenv("DB_USER", "root"),
#         password=os.getenv("DB_PASSWORD", ""),
#         pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
#         ssl=os.getenv("DB_SSL", "false").lower() == "true",
#     )
