"""Shared password hashing.

Flask-Bcrypt's hashing helpers are stateless: they wrap the `bcrypt` library
and do not need an application context. Keeping one instance here lets both the
Flask app and the ``User`` model use the same configured hasher without either
importing the other.
"""

from __future__ import annotations

from flask_bcrypt import Bcrypt

# Cost 12 is the Flask-Bcrypt default and is appropriate here.
bcrypt = Bcrypt()

__all__ = ["bcrypt"]
