"""
Shared rate limiter instance. Import `limiter` (not slowapi's Limiter class
directly) from route modules to keep every endpoint on the same limiter/key
function, and to avoid a circular import with main.py.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
