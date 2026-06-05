from __future__ import annotations
from datetime import datetime, timezone, date as date_type
from fastapi import APIRouter, HTTPException, status, Query, Depends
from app.models import (
    DeviceMaintenanceCreate, DeviceMaintenanceUpdate, DeviceMaintenanceClose,
    DeviceMaintenanceOut, MaintenanceStatus, MaintenanceType,
    MaintenanceConflictReservation, UserRole,
)
from app.cache import store
from app.auth import require_role
from app.services.conflict import (
    add_audit, check_maintenance_overlap, get_affected_reservations,
)
from app.models import AuditAction, ReservationStatus

router = APIRouter(prefix="/api/maintenance", tags=["设备维护停用管理"])


@router.post("", response_model=DeviceMaintenanceOut)
def create_maintenance(req: DeviceMaintenanceCreate, current_user: dict = Depends(require_role(UserRole.admin))):
    eq = store.equipment.get(req.equipment_id)
    if not eq:
        raise HTTPException(status_code=404, detail="设备不存在")
    if req.start_datetime >= req.end_datetime:
        raise HTTPException(status_code=400, detail="开始时间必须早于结束时间")
    if check_maintenance_overlap(req.equipment_id, req.start_datetime, req.end_datetime):
        raise HTTPException(status_code=409, detail="该设备在指定时段已存在维护单，时间重叠")

    mid = store.next_id("maintenance")
    now = datetime.now(timezone.utc)
    maintenance = {
        "id": mid,
        "equipment_id": req.equipment_id,
        "maintenance_type": req.maintenance_type,
        "reason": req.reason,
        "start_datetime": req.start_datetime,
        "end_datetime": req.end_datetime,
        "status": MaintenanceStatus.scheduled,
        "remark": req.remark,
        "creator_id": current_user["id"],
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    store.maintenance[mid] = maintenance

    affected = get_affected_reservations(mid)
    affected_info = f"，存在 {len(affected)} 个预约冲突" if affected else ""

    add_audit(
        reservation_id=None,
        action=AuditAction.maintenance_created,
        operator_id=current_user["id"],
        operator_role=current_user["role"],
        details=f"管理员 {current_user['username']} 创建维护单 {mid}，设备 {req.equipment_id}，类型 {req.maintenance_type.value}{affected_info}",
        maintenance_id=mid,
    )
    return DeviceMaintenanceOut(**maintenance)


@router.get("", response_model=list[DeviceMaintenanceOut])
def list_maintenance(
    equipment_id: str = Query(None),
    status_filter: MaintenanceStatus = Query(None, alias="status"),
    date_from: str = Query(None),
    date_to: str = Query(None),
    current_user: dict = Depends(require_role(UserRole.admin, UserRole.therapist)),
):
    results = list(store.maintenance.values())

    if equipment_id:
        results = [m for m in results if m["equipment_id"] == equipment_id]
    if status_filter:
        results = [m for m in results if m["status"] == status_filter]
    if date_from:
        try:
            d_from = date_type.fromisoformat(date_from)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"参数 date_from 格式错误，正确格式为 YYYY-MM-DD",
            )
        results = [m for m in results if m["start_datetime"].date() >= d_from]
    if date_to:
        try:
            d_to = date_type.fromisoformat(date_to)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"参数 date_to 格式错误，正确格式为 YYYY-MM-DD",
            )
        results = [m for m in results if m["start_datetime"].date() <= d_to]

    results.sort(key=lambda x: x["created_at"], reverse=True)
    return [DeviceMaintenanceOut(**m) for m in results]


@router.get("/calendar", response_model=list[DeviceMaintenanceOut])
def calendar_view(
    equipment_id: str = Query(None),
    date_from: str = Query(None),
    date_to: str = Query(None),
    status_filter: MaintenanceStatus = Query(None, alias="status"),
    current_user: dict = Depends(require_role(UserRole.admin, UserRole.therapist)),
):
    results = list(store.maintenance.values())

    if equipment_id:
        results = [m for m in results if m["equipment_id"] == equipment_id]
    if status_filter:
        results = [m for m in results if m["status"] == status_filter]

    if date_from:
        try:
            d_from = date_type.fromisoformat(date_from)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"参数 date_from 格式错误，正确格式为 YYYY-MM-DD",
            )
        from_dt = datetime(d_from.year, d_from.month, d_from.day, tzinfo=timezone.utc)
        results = [m for m in results if m["end_datetime"] > from_dt]

    if date_to:
        try:
            d_to = date_type.fromisoformat(date_to)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"参数 date_to 格式错误，正确格式为 YYYY-MM-DD",
            )
        to_dt = datetime(d_to.year, d_to.month, d_to.day, 23, 59, 59, tzinfo=timezone.utc)
        results = [m for m in results if m["start_datetime"] <= to_dt]

    results.sort(key=lambda x: x["start_datetime"])
    return [DeviceMaintenanceOut(**m) for m in results]


@router.get("/{maintenance_id}", response_model=DeviceMaintenanceOut)
def get_maintenance(maintenance_id: str, current_user: dict = Depends(require_role(UserRole.admin, UserRole.therapist))):
    m = store.maintenance.get(maintenance_id)
    if not m:
        raise HTTPException(status_code=404, detail="维护单不存在")
    return DeviceMaintenanceOut(**m)


@router.get("/{maintenance_id}/conflicts", response_model=list[MaintenanceConflictReservation])
def get_maintenance_conflicts(maintenance_id: str, current_user: dict = Depends(require_role(UserRole.admin))):
    m = store.maintenance.get(maintenance_id)
    if not m:
        raise HTTPException(status_code=404, detail="维护单不存在")
    affected = get_affected_reservations(maintenance_id)
    return [MaintenanceConflictReservation(**r) for r in affected]


@router.put("/{maintenance_id}", response_model=DeviceMaintenanceOut)
def update_maintenance(maintenance_id: str, req: DeviceMaintenanceUpdate, current_user: dict = Depends(require_role(UserRole.admin))):
    m = store.maintenance.get(maintenance_id)
    if not m:
        raise HTTPException(status_code=404, detail="维护单不存在")
    if m["status"] not in (MaintenanceStatus.scheduled, MaintenanceStatus.in_progress):
        raise HTTPException(status_code=400, detail="只能修改计划中或维护中的维护单")
    if m["version"] != req.version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"版本冲突：当前版本为 {m['version']}，提交版本为 {req.version}，请刷新后重试",
        )

    new_start = req.start_datetime if req.start_datetime is not None else m["start_datetime"]
    new_end = req.end_datetime if req.end_datetime is not None else m["end_datetime"]
    new_equipment_id = m["equipment_id"]

    if new_start >= new_end:
        raise HTTPException(status_code=400, detail="开始时间必须早于结束时间")

    if check_maintenance_overlap(new_equipment_id, new_start, new_end, exclude_maintenance_id=maintenance_id):
        raise HTTPException(status_code=409, detail="修改后的维护时段与该设备其他维护单时间重叠")

    if req.maintenance_type is not None:
        m["maintenance_type"] = req.maintenance_type
    if req.reason is not None:
        m["reason"] = req.reason
    if req.start_datetime is not None:
        m["start_datetime"] = req.start_datetime
    if req.end_datetime is not None:
        m["end_datetime"] = req.end_datetime
    if req.remark is not None:
        m["remark"] = req.remark
    if req.status is not None:
        if req.status == MaintenanceStatus.cancelled:
            raise HTTPException(status_code=400, detail="请使用关闭接口关闭维护单，不可通过修改接口取消")
        m["status"] = req.status

    m["version"] += 1
    m["updated_at"] = datetime.now(timezone.utc)

    affected = get_affected_reservations(maintenance_id)
    affected_info = f"，存在 {len(affected)} 个预约冲突" if affected else ""

    add_audit(
        reservation_id=None,
        action=AuditAction.maintenance_updated,
        operator_id=current_user["id"],
        operator_role=current_user["role"],
        details=f"管理员 {current_user['username']} 更新维护单 {maintenance_id}{affected_info}",
        maintenance_id=maintenance_id,
    )
    return DeviceMaintenanceOut(**m)


@router.put("/{maintenance_id}/close", response_model=DeviceMaintenanceOut)
def close_maintenance(maintenance_id: str, req: DeviceMaintenanceClose, current_user: dict = Depends(require_role(UserRole.admin))):
    m = store.maintenance.get(maintenance_id)
    if not m:
        raise HTTPException(status_code=404, detail="维护单不存在")
    if m["status"] not in (MaintenanceStatus.scheduled, MaintenanceStatus.in_progress):
        raise HTTPException(status_code=400, detail="只能关闭计划中或维护中的维护单")
    if m["version"] != req.version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"版本冲突：当前版本为 {m['version']}，提交版本为 {req.version}，请刷新后重试",
        )

    m["status"] = MaintenanceStatus.completed
    m["version"] += 1
    m["updated_at"] = datetime.now(timezone.utc)

    add_audit(
        reservation_id=None,
        action=AuditAction.maintenance_closed,
        operator_id=current_user["id"],
        operator_role=current_user["role"],
        details=f"管理员 {current_user['username']} 关闭维护单 {maintenance_id}，设备 {m['equipment_id']}",
        maintenance_id=maintenance_id,
    )
    return DeviceMaintenanceOut(**m)
