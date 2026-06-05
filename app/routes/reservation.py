from __future__ import annotations
from datetime import datetime, timezone, date as date_type
from fastapi import APIRouter, HTTPException, status, Query, Depends
from app.models import (
    ReservationCreate, ReservationChangeSlot, ReservationCancel,
    ReservationCheckIn, ReservationRelease, ReservationOut,
    ReservationStatus, AuditAction, UserRole, ConflictItem, ConflictReport,
)
from app.cache import store
from app.auth import require_role, get_current_user
from app.services.conflict import (
    check_equipment_slot_overlap, check_patient_time_overlap,
    add_audit, detect_all_conflicts, check_reservation_in_maintenance,
)

router = APIRouter(prefix="/api/reservations", tags=["预约管理"])


def _check_therapist_owner(reservation: dict, current_user: dict):
    if current_user["role"] == UserRole.admin:
        return
    if reservation["therapist_id"] != current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只能操作自己创建的预约",
        )


def _parse_date_param(value: str, param_name: str) -> date_type:
    try:
        return date_type.fromisoformat(value)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"参数 {param_name} 格式错误，正确格式为 YYYY-MM-DD，收到的值：{value}",
        )


@router.post("", response_model=ReservationOut)
def create_reservation(req: ReservationCreate, current_user: dict = Depends(require_role(UserRole.therapist))):
    eq = store.equipment.get(req.equipment_id)
    if not eq:
        raise HTTPException(status_code=404, detail="设备不存在")
    slot = store.time_slots.get(req.time_slot_id)
    if not slot:
        raise HTTPException(status_code=404, detail="时段不存在")
    if slot["equipment_id"] != req.equipment_id:
        raise HTTPException(status_code=400, detail="时段不属于指定设备")
    patient = store.users.get(req.patient_id)
    if not patient or patient["role"] != UserRole.patient:
        raise HTTPException(status_code=400, detail="患者ID无效")
    overlap = check_equipment_slot_overlap(req.equipment_id, slot["slot_date"], slot["start_time"], slot["end_time"])
    if overlap:
        raise HTTPException(status_code=409, detail="该设备此时段与已有预约时间重叠")
    patient_overlap = check_patient_time_overlap(req.patient_id, slot["slot_date"], slot["start_time"], slot["end_time"])
    if patient_overlap:
        raise HTTPException(status_code=409, detail="该患者在此时段已有预约（时间重叠）")
    maintenance_conflicts = check_reservation_in_maintenance(req.equipment_id, slot["slot_date"], slot["start_time"], slot["end_time"])
    if maintenance_conflicts:
        conflict_ids = [m["id"] for m in maintenance_conflicts]
        raise HTTPException(status_code=409, detail=f"该设备此时段处于维护中，维护单：{', '.join(conflict_ids)}")

    rid = store.next_id("reservation")
    now = datetime.now(timezone.utc)
    reservation = {
        "id": rid,
        "equipment_id": req.equipment_id,
        "time_slot_id": req.time_slot_id,
        "patient_id": req.patient_id,
        "therapist_id": current_user["id"],
        "status": ReservationStatus.reserved,
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    store.reservations[rid] = reservation
    slot["is_available"] = False
    add_audit(rid, AuditAction.created, current_user["id"], current_user["role"],
              f"治疗师 {current_user['username']} 为患者 {req.patient_id} 创建预约，设备 {req.equipment_id}，时段 {req.time_slot_id}")
    return ReservationOut(**reservation)


@router.get("", response_model=list[ReservationOut])
def list_reservations(
    equipment_id: str = Query(None),
    therapist_id: str = Query(None),
    patient_id: str = Query(None),
    status_filter: ReservationStatus = Query(None, alias="status"),
    date_from: str = Query(None),
    date_to: str = Query(None),
    current_user: dict = Depends(require_role(UserRole.admin, UserRole.therapist, UserRole.patient)),
):
    results = list(store.reservations.values())

    if current_user["role"] == UserRole.patient:
        results = [r for r in results if r["patient_id"] == current_user["id"]]

    if equipment_id:
        results = [r for r in results if r["equipment_id"] == equipment_id]
    if therapist_id:
        results = [r for r in results if r["therapist_id"] == therapist_id]
    if patient_id:
        results = [r for r in results if r["patient_id"] == patient_id]
    if status_filter:
        results = [r for r in results if r["status"] == status_filter]
    if date_from:
        d_from = _parse_date_param(date_from, "date_from")
        results = [r for r in results if (slot := store.time_slots.get(r["time_slot_id"])) and slot["slot_date"] >= d_from]
    if date_to:
        d_to = _parse_date_param(date_to, "date_to")
        results = [r for r in results if (slot := store.time_slots.get(r["time_slot_id"])) and slot["slot_date"] <= d_to]

    return [ReservationOut(**r) for r in results]


@router.get("/my", response_model=list[ReservationOut])
def my_reservations(current_user: dict = Depends(require_role(UserRole.patient))):
    results = [r for r in store.reservations.values() if r["patient_id"] == current_user["id"]]
    return [ReservationOut(**r) for r in results]


@router.get("/conflicts/check", response_model=ConflictReport)
def check_conflicts(current_user: dict = Depends(require_role(UserRole.admin, UserRole.therapist))):
    conflicts = detect_all_conflicts()
    return ConflictReport(conflicts=[ConflictItem(**c) for c in conflicts])


@router.get("/{reservation_id}", response_model=ReservationOut)
def get_reservation(reservation_id: str, current_user: dict = Depends(require_role(UserRole.admin, UserRole.therapist, UserRole.patient))):
    r = store.reservations.get(reservation_id)
    if not r:
        raise HTTPException(status_code=404, detail="预约不存在")
    if current_user["role"] == UserRole.patient and r["patient_id"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="无权查看该预约")
    return ReservationOut(**r)


@router.put("/{reservation_id}/time-slot", response_model=ReservationOut)
def change_time_slot(reservation_id: str, req: ReservationChangeSlot, current_user: dict = Depends(require_role(UserRole.therapist))):
    r = store.reservations.get(reservation_id)
    if not r:
        raise HTTPException(status_code=404, detail="预约不存在")
    _check_therapist_owner(r, current_user)
    if r["status"] not in (ReservationStatus.reserved,):
        raise HTTPException(status_code=400, detail="只能修改已预约状态的预约")
    if r["version"] != req.version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"版本冲突：当前版本为 {r['version']}，提交版本为 {req.version}，请刷新后重试",
        )
    new_slot = store.time_slots.get(req.new_time_slot_id)
    if not new_slot:
        raise HTTPException(status_code=404, detail="新时段不存在")
    if new_slot["equipment_id"] != r["equipment_id"]:
        raise HTTPException(status_code=400, detail="新时段不属于同一设备")
    if check_equipment_slot_overlap(r["equipment_id"], new_slot["slot_date"], new_slot["start_time"], new_slot["end_time"], exclude_reservation_id=reservation_id):
        raise HTTPException(status_code=409, detail="新时段与该设备已有预约时间重叠")
    if check_patient_time_overlap(r["patient_id"], new_slot["slot_date"], new_slot["start_time"], new_slot["end_time"], exclude_reservation_id=reservation_id):
        raise HTTPException(status_code=409, detail="该患者在新时段已有预约（时间重叠）")
    maintenance_conflicts = check_reservation_in_maintenance(r["equipment_id"], new_slot["slot_date"], new_slot["start_time"], new_slot["end_time"])
    if maintenance_conflicts:
        conflict_ids = [m["id"] for m in maintenance_conflicts]
        raise HTTPException(status_code=409, detail=f"新时段处于设备维护中，维护单：{', '.join(conflict_ids)}")

    old_slot_id = r["time_slot_id"]
    old_slot = store.time_slots.get(old_slot_id)
    if old_slot:
        old_slot["is_available"] = True

    r["time_slot_id"] = req.new_time_slot_id
    r["version"] += 1
    r["updated_at"] = datetime.now(timezone.utc)
    new_slot["is_available"] = False

    add_audit(reservation_id, AuditAction.time_changed, current_user["id"], current_user["role"],
              f"治疗师 {current_user['username']} 将预约从时段 {old_slot_id} 改为 {req.new_time_slot_id}")
    return ReservationOut(**r)


@router.put("/{reservation_id}/cancel", response_model=ReservationOut)
def cancel_reservation(reservation_id: str, req: ReservationCancel, current_user: dict = Depends(require_role(UserRole.therapist))):
    r = store.reservations.get(reservation_id)
    if not r:
        raise HTTPException(status_code=404, detail="预约不存在")
    _check_therapist_owner(r, current_user)
    if r["status"] not in (ReservationStatus.reserved,):
        raise HTTPException(status_code=400, detail="只能取消已预约状态的预约")
    if r["version"] != req.version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"版本冲突：当前版本为 {r['version']}，提交版本为 {req.version}，请刷新后重试",
        )
    r["status"] = ReservationStatus.cancelled
    r["version"] += 1
    r["updated_at"] = datetime.now(timezone.utc)

    slot = store.time_slots.get(r["time_slot_id"])
    if slot:
        slot["is_available"] = True

    add_audit(reservation_id, AuditAction.cancelled, current_user["id"], current_user["role"],
              f"治疗师 {current_user['username']} 取消了预约")
    return ReservationOut(**r)


@router.put("/{reservation_id}/checkin", response_model=ReservationOut)
def checkin_reservation(reservation_id: str, req: ReservationCheckIn, current_user: dict = Depends(require_role(UserRole.therapist))):
    r = store.reservations.get(reservation_id)
    if not r:
        raise HTTPException(status_code=404, detail="预约不存在")
    _check_therapist_owner(r, current_user)
    if r["status"] != ReservationStatus.reserved:
        raise HTTPException(status_code=400, detail="只能对已预约状态的记录签到")
    if r["version"] != req.version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"版本冲突：当前版本为 {r['version']}，提交版本为 {req.version}，请刷新后重试",
        )
    slot = store.time_slots.get(r["time_slot_id"])
    if slot:
        maintenance_conflicts = check_reservation_in_maintenance(r["equipment_id"], slot["slot_date"], slot["start_time"], slot["end_time"])
        if maintenance_conflicts:
            conflict_ids = [m["id"] for m in maintenance_conflicts]
            raise HTTPException(status_code=409, detail=f"该设备此时段处于维护中，无法签到，维护单：{', '.join(conflict_ids)}")
    r["status"] = ReservationStatus.checked_in
    r["version"] += 1
    r["updated_at"] = datetime.now(timezone.utc)

    add_audit(reservation_id, AuditAction.checked_in, current_user["id"], current_user["role"],
              f"治疗师 {current_user['username']} 确认患者 {r['patient_id']} 签到")
    return ReservationOut(**r)


@router.put("/{reservation_id}/release", response_model=ReservationOut)
def release_reservation(reservation_id: str, req: ReservationRelease, current_user: dict = Depends(require_role(UserRole.therapist))):
    r = store.reservations.get(reservation_id)
    if not r:
        raise HTTPException(status_code=404, detail="预约不存在")
    _check_therapist_owner(r, current_user)
    if r["status"] != ReservationStatus.checked_in:
        raise HTTPException(status_code=400, detail="只能释放已签到的记录")
    if r["version"] != req.version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"版本冲突：当前版本为 {r['version']}，提交版本为 {req.version}，请刷新后重试",
        )
    r["status"] = ReservationStatus.released
    r["version"] += 1
    r["updated_at"] = datetime.now(timezone.utc)

    slot = store.time_slots.get(r["time_slot_id"])
    if slot:
        slot["is_available"] = True

    add_audit(reservation_id, AuditAction.released, current_user["id"], current_user["role"],
              f"治疗师 {current_user['username']} 释放了设备，患者 {r['patient_id']} 完成训练")
    return ReservationOut(**r)
