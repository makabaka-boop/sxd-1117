from __future__ import annotations
from datetime import datetime, date, timezone
from app.cache import store
from app.models import ReservationStatus, AuditAction, UserRole


def add_audit(reservation_id: str, action: AuditAction, operator_id: str, operator_role: UserRole, details: str):
    log_id = store.next_id("audit")
    store.audit_logs[log_id] = {
        "id": log_id,
        "reservation_id": reservation_id,
        "action": action,
        "operator_id": operator_id,
        "operator_role": operator_role,
        "details": details,
        "created_at": datetime.now(timezone.utc),
    }


def find_slot_conflicts() -> list[dict]:
    conflicts = []
    slot_reservations: dict[str, list[dict]] = {}
    for r in store.reservations.values():
        if r["status"] in (ReservationStatus.reserved, ReservationStatus.checked_in):
            key = r["time_slot_id"]
            slot_reservations.setdefault(key, []).append(r)

    for slot_id, reservations in slot_reservations.items():
        if len(reservations) > 1:
            conflicts.append({
                "type": "slot_conflict",
                "message": f"时段 {slot_id} 存在 {len(reservations)} 个有效预约",
                "related_ids": [r["id"] for r in reservations],
            })
    return conflicts


def find_duplicate_patient_reservations() -> list[dict]:
    conflicts = []
    patient_slot: dict[str, list[dict]] = {}
    for r in store.reservations.values():
        if r["status"] in (ReservationStatus.reserved, ReservationStatus.checked_in):
            key = f"{r['patient_id']}_{r['time_slot_id']}"
            patient_slot.setdefault(key, []).append(r)

    for key, reservations in patient_slot.items():
        if len(reservations) > 1:
            patient_id = reservations[0]["patient_id"]
            slot_id = reservations[0]["time_slot_id"]
            conflicts.append({
                "type": "duplicate_reservation",
                "message": f"患者 {patient_id} 在时段 {slot_id} 存在重复预约",
                "related_ids": [r["id"] for r in reservations],
            })
    return conflicts


def find_release_omissions() -> list[dict]:
    conflicts = []
    now = datetime.now(timezone.utc)
    for r in store.reservations.values():
        if r["status"] == ReservationStatus.checked_in:
            slot = store.time_slots.get(r["time_slot_id"])
            if slot:
                slot_end = datetime.combine(slot["slot_date"], slot["end_time"], tzinfo=timezone.utc)
                if now > slot_end:
                    conflicts.append({
                        "type": "release_omission",
                        "message": f"预约 {r['id']} 已超过时段结束时间但尚未释放",
                        "related_ids": [r["id"]],
                    })
    return conflicts


def detect_all_conflicts() -> list[dict]:
    return find_slot_conflicts() + find_duplicate_patient_reservations() + find_release_omissions()


def check_slot_available(time_slot_id: str, exclude_reservation_id: str = None) -> bool:
    for r in store.reservations.values():
        if r["time_slot_id"] == time_slot_id and r["status"] in (ReservationStatus.reserved, ReservationStatus.checked_in):
            if exclude_reservation_id and r["id"] == exclude_reservation_id:
                continue
            return False
    return True


def check_patient_duplicate(patient_id: str, time_slot_id: str, exclude_reservation_id: str = None) -> bool:
    for r in store.reservations.values():
        if r["patient_id"] == patient_id and r["time_slot_id"] == time_slot_id and r["status"] in (ReservationStatus.reserved, ReservationStatus.checked_in):
            if exclude_reservation_id and r["id"] == exclude_reservation_id:
                continue
            return True
    return False
