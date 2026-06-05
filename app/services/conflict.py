from __future__ import annotations
from datetime import datetime, date, time, timezone
from app.cache import store
from app.models import ReservationStatus, AuditAction, UserRole, MaintenanceStatus


def add_audit(reservation_id: str | None, action: AuditAction, operator_id: str, operator_role: UserRole, details: str, maintenance_id: str | None = None):
    log_id = store.next_id("audit")
    store.audit_logs[log_id] = {
        "id": log_id,
        "reservation_id": reservation_id,
        "maintenance_id": maintenance_id,
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
    return find_slot_conflicts() + find_duplicate_patient_reservations() + find_release_omissions() + find_maintenance_reservation_conflicts()


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _datetime_range_overlap(start1: datetime, end1: datetime, start2: datetime, end2: datetime) -> bool:
    return _ensure_utc(start1) < _ensure_utc(end2) and _ensure_utc(start2) < _ensure_utc(end1)


def check_maintenance_overlap(equipment_id: str, start_dt: datetime, end_dt: datetime, exclude_maintenance_id: str | None = None) -> bool:
    for m in store.maintenance.values():
        if m["equipment_id"] != equipment_id:
            continue
        if m["status"] not in (MaintenanceStatus.scheduled, MaintenanceStatus.in_progress):
            continue
        if exclude_maintenance_id and m["id"] == exclude_maintenance_id:
            continue
        if _datetime_range_overlap(start_dt, end_dt, m["start_datetime"], m["end_datetime"]):
            return True
    return False


def check_reservation_in_maintenance(equipment_id: str, slot_date: date, start_time: time, end_time: time) -> list[dict]:
    conflicting = []
    slot_start = datetime.combine(slot_date, start_time, tzinfo=timezone.utc)
    slot_end = datetime.combine(slot_date, end_time, tzinfo=timezone.utc)
    for m in store.maintenance.values():
        if m["equipment_id"] != equipment_id:
            continue
        if m["status"] not in (MaintenanceStatus.scheduled, MaintenanceStatus.in_progress):
            continue
        if _datetime_range_overlap(slot_start, slot_end, m["start_datetime"], m["end_datetime"]):
            conflicting.append(m)
    return conflicting


def find_maintenance_reservation_conflicts() -> list[dict]:
    conflicts = []
    for m in store.maintenance.values():
        if m["status"] not in (MaintenanceStatus.scheduled, MaintenanceStatus.in_progress):
            continue
        for r in store.reservations.values():
            if r["status"] not in (ReservationStatus.reserved, ReservationStatus.checked_in):
                continue
            if r["equipment_id"] != m["equipment_id"]:
                continue
            slot = store.time_slots.get(r["time_slot_id"])
            if not slot:
                continue
            slot_start = datetime.combine(slot["slot_date"], slot["start_time"], tzinfo=timezone.utc)
            slot_end = datetime.combine(slot["slot_date"], slot["end_time"], tzinfo=timezone.utc)
            if _datetime_range_overlap(slot_start, slot_end, m["start_datetime"], m["end_datetime"]):
                conflicts.append({
                    "type": "maintenance_conflict",
                    "message": f"设备 {m['equipment_id']} 的维护单 {m['id']} 与预约 {r['id']} 时间重叠",
                    "related_ids": [m["id"], r["id"]],
                })
    return conflicts


def get_affected_reservations(maintenance_id: str) -> list[dict]:
    m = store.maintenance.get(maintenance_id)
    if not m:
        return []
    affected = []
    for r in store.reservations.values():
        if r["status"] not in (ReservationStatus.reserved, ReservationStatus.checked_in):
            continue
        if r["equipment_id"] != m["equipment_id"]:
            continue
        slot = store.time_slots.get(r["time_slot_id"])
        if not slot:
            continue
        slot_start = datetime.combine(slot["slot_date"], slot["start_time"], tzinfo=timezone.utc)
        slot_end = datetime.combine(slot["slot_date"], slot["end_time"], tzinfo=timezone.utc)
        if _datetime_range_overlap(slot_start, slot_end, m["start_datetime"], m["end_datetime"]):
            affected.append({
                "reservation_id": r["id"],
                "equipment_id": r["equipment_id"],
                "patient_id": r["patient_id"],
                "therapist_id": r["therapist_id"],
                "status": r["status"],
                "slot_date": slot["slot_date"],
                "start_time": slot["start_time"],
                "end_time": slot["end_time"],
            })
    return affected
