from __future__ import annotations
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, status, Query, Depends
from app.models import (
    ReservationCreate, ReservationChangeSlot, ReservationCancel,
    ReservationCheckIn, ReservationRelease, ReservationOut,
    ReservationStatus, AuditAction, UserRole, ConflictItem, ConflictReport,
)
from app.cache import store
from app.auth import require_role, get_current_user
from app.services.conflict import (
    check_slot_available, check_patient_duplicate,
    add_audit, detect_all_conflicts,
)

router = APIRouter(prefix="/api/reservations", tags=["预约管理"])


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
    if not check_slot_available(req.time_slot_id):
        raise HTTPException(status_code=409, detail="该时段已被预约")
    if check_patient_duplicate(req.patient_id, req.time_slot_id):
        raise HTTPException(status_code=409, detail="该患者在此时段已有预约")

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
        from datetime import date as date_type
        d_from = date_type.fromisoformat(date_from)
        filtered = []
        for r in results:
            slot = store.time_slots.get(r["time_slot_id"])
            if slot and slot["slot_date"] >= d_from:
                filtered.append(r)
        results = filtered
    if date_to:
        from datetime import date as date_type
        d_to = date_type.fromisoformat(date_to)
        filtered = []
        for r in results:
            slot = store.time_slots.get(r["time_slot_id"])
            if slot and slot["slot_date"] <= d_to:
                filtered.append(r)
        results = filtered

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
    if not check_slot_available(req.new_time_slot_id):
        raise HTTPException(status_code=409, detail="新时段已被预约")
    if check_patient_duplicate(r["patient_id"], req.new_time_slot_id, exclude_reservation_id=reservation_id):
        raise HTTPException(status_code=409, detail="该患者在新时段已有预约")

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
    if r["status"] != ReservationStatus.reserved:
        raise HTTPException(status_code=400, detail="只能对已预约状态的记录签到")
    if r["version"] != req.version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"版本冲突：当前版本为 {r['version']}，提交版本为 {req.version}，请刷新后重试",
        )
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
