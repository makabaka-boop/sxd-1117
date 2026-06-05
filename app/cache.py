import threading
from datetime import datetime, date, time
from app.models import UserRole, ReservationStatus


class _Store:
    def __init__(self):
        self._lock = threading.Lock()
        self.users: dict = {}
        self.equipment: dict = {}
        self.time_slots: dict = {}
        self.reservations: dict = {}
        self.audit_logs: dict = {}
        self.maintenance: dict = {}
        self._counters = {
            "user": 0,
            "equipment": 0,
            "time_slot": 0,
            "reservation": 0,
            "audit": 0,
            "maintenance": 0,
        }

    def next_id(self, prefix: str) -> str:
        with self._lock:
            self._counters[prefix] += 1
            return f"{prefix}_{self._counters[prefix]}"

    def lock(self) -> threading.Lock:
        return self._lock


store = _Store()


def _seed():
    from passlib.hash import bcrypt as passlib_bcrypt

    admin = {
        "id": store.next_id("user"),
        "username": "admin",
        "password_hash": passlib_bcrypt.hash("admin123"),
        "role": UserRole.admin,
    }
    store.users[admin["id"]] = admin

    therapist1 = {
        "id": store.next_id("user"),
        "username": "therapist1",
        "password_hash": passlib_bcrypt.hash("therapist123"),
        "role": UserRole.therapist,
    }
    store.users[therapist1["id"]] = therapist1

    therapist2 = {
        "id": store.next_id("user"),
        "username": "therapist2",
        "password_hash": passlib_bcrypt.hash("therapist123"),
        "role": UserRole.therapist,
    }
    store.users[therapist2["id"]] = therapist2

    patient1 = {
        "id": store.next_id("user"),
        "username": "patient1",
        "password_hash": passlib_bcrypt.hash("patient123"),
        "role": UserRole.patient,
    }
    store.users[patient1["id"]] = patient1

    patient2 = {
        "id": store.next_id("user"),
        "username": "patient2",
        "password_hash": passlib_bcrypt.hash("patient123"),
        "role": UserRole.patient,
    }
    store.users[patient2["id"]] = patient2


try:
    _seed()
except Exception:
    pass
