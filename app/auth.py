"""Users, passwords, sessions and roles.

Roles, from least to most access:
  staff    record sales, receive deliveries, counts and waste, see the menu and the schedule
  manager  everything day to day: menu, ingredients, ordering, schedule, imports, Excel
  owner    also managers' and owners' accounts, settings and backups
(Managers can add staff accounts and reset staff passwords.)

Users live in data/users.json, apart from the catalog, so the catalog and the Excel
workbook never carry password hashes. Passwords are stored as salted PBKDF2-SHA256.
Sessions are kept in memory (signing in again after a restart is expected).
"""

import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import threading
import time
from datetime import datetime

from .store import DATA_DIR, ValidationError

USERS_FILE = os.path.join(DATA_DIR, "users.json")
ROLES = ["staff", "manager", "owner"]
RANK = {r: i for i, r in enumerate(ROLES, start=1)}
ITERATIONS = 310_000
SESSION_HOURS = 12
MIN_PASSWORD = 8
MAX_FAILURES, LOCKOUT_SECONDS = 5, 300


def hash_password(password, salt=None, iterations=ITERATIONS):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), iterations).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def check_password(password, stored):
    try:
        _algo, iterations, salt, digest = stored.split("$")
        return hmac.compare_digest(hash_password(password, salt, int(iterations)).split("$")[3], digest)
    except (ValueError, AttributeError):
        return False


def _clean_username(value):
    name = str(value or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9._-]{2,32}", name):
        raise ValidationError("Username: 2-32 letters, numbers, dots, dashes or underscores")
    return name


def _check_new_password(pw):
    if len(pw or "") < MIN_PASSWORD:
        raise ValidationError(f"Password must be at least {MIN_PASSWORD} characters")


class Users:
    def __init__(self, path=USERS_FILE):
        self.path = path
        self.lock = threading.RLock()
        self.sessions = {}   # token -> {"username", "expires"}
        self.failures = {}   # (ip, username) -> [count, first_failure_time]
        self.users = self._load()

    # ---------------------------------------------------------------- io
    def _load(self):
        if not os.path.exists(self.path):
            return []
        with open(self.path, encoding="utf-8") as f:
            return json.load(f)

    def save(self):
        with self.lock:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.users, f, indent=2)
            os.replace(tmp, self.path)
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass

    # ------------------------------------------------------------ lookups
    def get(self, username):
        username = str(username or "").strip().lower()
        return next((u for u in self.users if u["username"] == username), None)

    @staticmethod
    def public(user):
        return {k: v for k, v in user.items() if k != "password"}

    def needs_setup(self):
        return not any(u["active"] for u in self.users)

    # ----------------------------------------------------------- changes
    def create(self, username, password, name="", role="staff", employee_id="", must_change=True):
        """New account. A password chosen by someone else is temporary: the user must replace it
        at their first sign-in (must_change)."""
        with self.lock:
            username = _clean_username(username)
            if self.get(username):
                raise ValidationError(f"The username '{username}' is taken")
            if role not in ROLES:
                raise ValidationError(f"Role must be one of: {', '.join(ROLES)}")
            _check_new_password(password)
            user = {"username": username, "name": str(name or username).strip(), "role": role,
                    "employee_id": employee_id or "", "active": True, "password": hash_password(password),
                    "must_change": bool(must_change),
                    "created": datetime.now().isoformat(timespec="minutes")}
            self.users.append(user)
            self.save()
            return user

    def update(self, username, changes, keep_token=None):
        with self.lock:
            user = self.get(username)
            if not user:
                raise ValidationError("User not found")
            if "role" in changes and changes["role"] not in ROLES:
                raise ValidationError(f"Role must be one of: {', '.join(ROLES)}")
            demoting = user["role"] == "owner" and (changes.get("role", "owner") != "owner" or changes.get("active") is False)
            if demoting and sum(1 for u in self.users if u["role"] == "owner" and u["active"]) <= 1:
                raise ValidationError("There must always be at least one active owner")
            for key in ("name", "role", "employee_id"):
                if key in changes:
                    user[key] = str(changes[key] or "").strip()
            if "active" in changes:
                user["active"] = bool(changes["active"])
                if not user["active"]:
                    self.end_sessions(username)
            if changes.get("password"):
                _check_new_password(changes["password"])
                user["password"] = hash_password(changes["password"])
                user["must_change"] = bool(changes.get("must_change", True))  # a reset password is temporary
                self.end_sessions(username, keep=keep_token)
            self.save()
            return user

    def change_own_password(self, username, current, new, keep_token=None):
        """Signs out the user's other sessions but keeps the one they are using."""
        user = self.get(username)
        if not user or not check_password(current or "", user["password"]):
            raise ValidationError("Current password is not right")
        if new == current:
            raise ValidationError("Choose a password different from the current one")
        return self.update(username, {"password": new, "must_change": False}, keep_token=keep_token)

    # ---------------------------------------------------------- sessions
    def login(self, username, password, ip):
        key = (ip, str(username or "").strip().lower())
        with self.lock:
            count, first = self.failures.get(key, (0, 0))
            if first and time.time() - first >= LOCKOUT_SECONDS:  # old failures expire
                count, first = 0, 0
            if count >= MAX_FAILURES:
                raise ValidationError("Too many attempts. Wait a few minutes and try again.")
            user = self.get(username)
            # check a hash even for unknown users so response time doesn't reveal which usernames exist
            ok = check_password(password or "", user["password"] if user else hash_password("x"))
            if not (user and user["active"] and ok):
                self.failures[key] = (count + 1, first or time.time())
                raise ValidationError("Wrong username or password")
            self.failures.pop(key, None)
            token = secrets.token_urlsafe(32)
            self.sessions[token] = {"username": user["username"], "expires": time.time() + SESSION_HOURS * 3600}
            user["last_login"] = datetime.now().isoformat(timespec="minutes")
            self.save()
            return token, user

    def session_user(self, token):
        with self.lock:
            s = self.sessions.get(token or "")
            if not s or s["expires"] < time.time():
                self.sessions.pop(token or "", None)
                return None
            user = self.get(s["username"])
            if not user or not user["active"]:
                return None
            s["expires"] = time.time() + SESSION_HOURS * 3600  # sliding expiry
            return user

    def logout(self, token):
        with self.lock:
            self.sessions.pop(token or "", None)

    def end_sessions(self, username, keep=None):
        with self.lock:
            for t in [t for t, s in self.sessions.items() if s["username"] == username and t != keep]:
                del self.sessions[t]


def main(argv):
    """python -m app.auth add <username> <role> | password <username> | list"""
    import getpass
    users = Users()
    if len(argv) >= 3 and argv[0] == "add":
        pw = getpass.getpass("Password: ")
        users.create(argv[1], pw, name=argv[1], role=argv[2], must_change=False)
        print(f"Created {argv[1]} ({argv[2]})")
    elif len(argv) == 2 and argv[0] == "password":
        pw = getpass.getpass("New password: ")
        users.update(argv[1], {"password": pw, "active": True, "must_change": False})
        print(f"Password changed for {argv[1]}")
    elif argv[:1] == ["list"]:
        for u in users.users:
            print(f"{u['username']:20} {u['role']:8} {'active' if u['active'] else 'disabled'}")
    else:
        print(main.__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
