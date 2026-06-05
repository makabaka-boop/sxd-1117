from __future__ import annotations
from fastapi import APIRouter, HTTPException, status, Depends
from app.models import (
    EquipmentCreate, EquipmentUpdate, EquipmentOut,
    TimeSlotCreate, TimeSlotUpdate, TimeSlotOut,
    UserRole,
)
from app.cache import store
from app.auth import require_role

router = APIRouter(prefix="/api", tags=["设备与时段"])


@router.post("/equipment", response_model=EquipmentOut)
def create_equipment(req: EquipmentCreate, current_user: dict = Depends(require_role(UserRole.admin))):
    eid = store.next_id("equipment")
    eq = {
        "id": eid,
        "name": req.name,
        "description": req.description,
        "version": 1,
    }
    store.equipment[eid] = eq
    return EquipmentOut(**eq)


@router.get("/equipment", response_model=list[EquipmentOut])
def list_equipment():
    return [EquipmentOut(**eq) for eq in store.equipment.values()]


@router.get("/equipment/{equipment_id}", response_model=EquipmentOut)
def get_equipment(equipment_id: str):
    eq = store.equipment.get(equipment_id)
    if not eq:
        raise HTTPException(status_code=404, detail="设备不存在")
    return EquipmentOut(**eq)


@router.put("/equipment/{equipment_id}", response_model=EquipmentOut)
def update_equipment(equipment_id: str, req: EquipmentUpdate, current_user: dict = Depends(require_role(UserRole.admin))):
    eq = store.equipment.get(equipment_id)
    if not eq:
        raise HTTPException(status_code=404, detail="设备不存在")
    if eq["version"] != req.version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"版本冲突：当前版本为 {eq['version']}，提交版本为 {req.version}",
        )
    if req.name is not None:
        eq["name"] = req.name
    if req.description is not None:
        eq["description"] = req.description
    eq["version"] += 1
    return EquipmentOut(**eq)


@router.post("/time-slots", response_model=TimeSlotOut)
def create_time_slot(req: TimeSlotCreate, current_user: dict = Depends(require_role(UserRole.admin))):
    eq = store.equipment.get(req.equipment_id)
    if not eq:
        raise HTTPException(status_code=404, detail="设备不存在")
    if req.start_time >= req.end_time:
        raise HTTPException(status_code=400, detail="开始时间必须早于结束时间")
    sid = store.next_id("time_slot")
    slot = {
        "id": sid,
        "equipment_id": req.equipment_id,
        "slot_date": req.slot_date,
        "start_time": req.start_time,
        "end_time": req.end_time,
        "is_available": True,
        "version": 1,
    }
    store.time_slots[sid] = slot
    return TimeSlotOut(**slot)


@router.get("/time-slots", response_model=list[TimeSlotOut])
def list_time_slots(equipment_id: str = None, slot_date: str = None):
    results = list(store.time_slots.values())
    if equipment_id:
        results = [s for s in results if s["equipment_id"] == equipment_id]
    if slot_date:
        from datetime import date as date_type
        d = date_type.fromisoformat(slot_date)
        results = [s for s in results if s["slot_date"] == d]
    return [TimeSlotOut(**s) for s in results]


@router.get("/time-slots/{slot_id}", response_model=TimeSlotOut)
def get_time_slot(slot_id: str):
    slot = store.time_slots.get(slot_id)
    if not slot:
        raise HTTPException(status_code=404, detail="时段不存在")
    return TimeSlotOut(**slot)


@router.put("/time-slots/{slot_id}", response_model=TimeSlotOut)
def update_time_slot(slot_id: str, req: TimeSlotUpdate, current_user: dict = Depends(require_role(UserRole.admin))):
    slot = store.time_slots.get(slot_id)
    if not slot:
        raise HTTPException(status_code=404, detail="时段不存在")
    if slot["version"] != req.version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"版本冲突：当前版本为 {slot['version']}，提交版本为 {req.version}",
        )
    if req.slot_date is not None:
        slot["slot_date"] = req.slot_date
    if req.start_time is not None:
        slot["start_time"] = req.start_time
    if req.end_time is not None:
        slot["end_time"] = req.end_time
    slot["version"] += 1
    return TimeSlotOut(**slot)


@router.delete("/time-slots/{slot_id}", status_code=204)
def delete_time_slot(slot_id: str, current_user: dict = Depends(require_role(UserRole.admin))):
    slot = store.time_slots.get(slot_id)
    if not slot:
        raise HTTPException(status_code=404, detail="时段不存在")
    from app.models import ReservationStatus
    for r in store.reservations.values():
        if r["time_slot_id"] == slot_id and r["status"] in (ReservationStatus.reserved, ReservationStatus.checked_in):
            raise HTTPException(status_code=400, detail="该时段存在有效预约，无法删除")
    del store.time_slots[slot_id]
