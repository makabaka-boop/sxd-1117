from __future__ import annotations
from datetime import datetime, date, time, timezone
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


def _time_ranges_overlap(d1: date, s1: time, e1: time, d2: date, s2: time, e2: time) -> bool:
    if d1 != d2:
        return False
    return s1 < e2 and s2 < e1


def check_equipment_slot_overlap(equipment_id: str, slot_date: date, start_time: time, end_time: time, exclude_reservation_id: str = None) -> bool:
    for r in store.reservations.values():
        if r["status"] not in (ReservationStatus.reserved, ReservationStatus.checked_in):
            continue
        if r["equipment_id"] != equipment_id:
            continue
        if exclude_reservation_id and r["id"] == exclude_reservation_id:
            continue
        slot = store.time_slots.get(r["time_slot_id"])
        if not slot:
            continue
        if _time_ranges_overlap(slot_date, start_time, end_time, slot["slot_date"], slot["start_time"], slot["end_time"]):
            return True
    return False


def check_patient_time_overlap(patient_id: str, slot_date: date, start_time: time, end_time: time, exclude_reservation_id: str = None) -> bool:
    for r in store.reservations.values():
        if r["status"] not in (ReservationStatus.reserved, ReservationStatus.checked_in):
            continue
        if r["patient_id"] != patient_id:
            continue
        if exclude_reservation_id and r["id"] == exclude_reservation_id:
            continue
        slot = store.time_slots.get(r["time_slot_id"])
        if not slot:
            continue
        if _time_ranges_overlap(slot_date, start_time, end_time, slot["slot_date"], slot["start_time"], slot["end_time"]):
            return True
    return False


def find_slot_conflicts() -> list[dict]:
    conflicts = []
    active = [r for r in store.reservations.values() if r["status"] in (ReservationStatus.reserved, ReservationStatus.checked_in)]
    seen = set()
    for i, r1 in enumerate(active):
        slot1 = store.time_slots.get(r1["time_slot_id"])
        if not slot1:
            continue
        for j, r2 in enumerate(active):
            if j <= i:
                continue
            if r1["equipment_id"] != r2["equipment_id"]:
                continue
            slot2 = store.time_slots.get(r2["time_slot_id"])
            if not slot2:
                continue
            pair_key = tuple(sorted([r1["id"], r2["id"]]))
            if pair_key in seen:
                continue
            if _time_ranges_overlap(slot1["slot_date"], slot1["start_time"], slot1["end_time"],
                                    slot2["slot_date"], slot2["start_time"], slot2["end_time"]):
                seen.add(pair_key)
                conflicts.append({
                    "type": "slot_conflict",
                    "message": f"设备 {r1['equipment_id']} 上预约 {r1['id']} 与 {r2['id']} 时段重叠",
                    "related_ids": [r1["id"], r2["id"]],
                })
    return conflicts


def find_duplicate_patient_reservations() -> list[dict]:
    conflicts = []
    active = [r for r in store.reservations.values() if r["status"] in (ReservationStatus.reserved, ReservationStatus.checked_in)]
    seen = set()
    for i, r1 in enumerate(active):
        slot1 = store.time_slots.get(r1["time_slot_id"])
        if not slot1:
            continue
        for j, r2 in enumerate(active):
            if j <= i:
                continue
            if r1["patient_id"] != r2["patient_id"]:
                continue
            slot2 = store.time_slots.get(r2["time_slot_id"])
            if not slot2:
                continue
            pair_key = tuple(sorted([r1["id"], r2["id"]]))
            if pair_key in seen:
                continue
            if _time_ranges_overlap(slot1["slot_date"], slot1["start_time"], slot1["end_time"],
                                    slot2["slot_date"], slot2["start_time"], slot2["end_time"]):
                seen.add(pair_key)
                conflicts.append({
                    "type": "duplicate_reservation",
                    "message": f"患者 {r1['patient_id']} 的预约 {r1['id']} 与 {r2['id']} 时间重叠（跨设备）",
                    "related_ids": [r1["id"], r2["id"]],
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
