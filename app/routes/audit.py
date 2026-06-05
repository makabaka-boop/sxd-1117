from __future__ import annotations
from fastapi import APIRouter, Query, Depends
from app.models import AuditLogOut, UserRole
from app.cache import store
from app.auth import require_role

router = APIRouter(prefix="/api/audit", tags=["审计日志"])


@router.get("", response_model=list[AuditLogOut])
def list_audit_logs(
    reservation_id: str = Query(None),
    maintenance_id: str = Query(None),
    operator_id: str = Query(None),
    action: str = Query(None),
    current_user: dict = Depends(require_role(UserRole.admin, UserRole.therapist)),
):
    results = list(store.audit_logs.values())
    if reservation_id:
        results = [l for l in results if l.get("reservation_id") == reservation_id]
    if maintenance_id:
        results = [l for l in results if l.get("maintenance_id") == maintenance_id]
    if operator_id:
        results = [l for l in results if l["operator_id"] == operator_id]
    if action:
        results = [l for l in results if l["action"].value == action]
    results.sort(key=lambda x: x["created_at"], reverse=True)
    return [AuditLogOut(**l) for l in results]
