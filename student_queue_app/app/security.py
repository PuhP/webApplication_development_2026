from functools import wraps

from flask import abort
from flask_login import current_user


def role_required(*roles: str):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated or current_user.role not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def can_manage_queue(user) -> bool:
    return user.is_authenticated and user.role in {"teacher", "admin"}


def can_manage_admin(user) -> bool:
    return user.is_authenticated and user.role == "admin"
