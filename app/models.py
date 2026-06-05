from __future__ import annotations
from enum import Enum
from datetime import datetime, date, time
from pydantic import BaseModel, Field
from typing import Optional


class UserRole(str, Enum):
    admin = "admin"
    therapist = "therapist"
    patient = "patient"


class ReservationStatus(str, Enum):
    reserved = "reserved"
    checked_in = "checked_in"
    released = "released"
    cancelled = "cancelled"


class AuditAction(str, Enum):
    created = "created"
    time_changed = "time_changed"
    cancelled = "cancelled"
    checked_in = "checked_in"
    released = "released"
    maintenance_created = "maintenance_created"
    maintenance_updated = "maintenance_updated"
    maintenance_closed = "maintenance_closed"


class MaintenanceType(str, Enum):
    preventive = "preventive"
    corrective = "corrective"
    calibration = "calibration"
    other = "other"


class MaintenanceStatus(str, Enum):
    scheduled = "scheduled"
    in_progress = "in_progress"
    completed = "completed"
    cancelled = "cancelled"


class UserCreate(BaseModel):
    username: str
    password: str
    role: UserRole


class UserOut(BaseModel):
    id: str
    username: str
    role: UserRole


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class EquipmentCreate(BaseModel):
    name: str
    description: str = ""


class EquipmentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    version: int


class EquipmentOut(BaseModel):
    id: str
    name: str
    description: str
    version: int


class TimeSlotCreate(BaseModel):
    equipment_id: str
    slot_date: date
    start_time: time
    end_time: time


class TimeSlotUpdate(BaseModel):
    slot_date: Optional[date] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    version: int


class TimeSlotOut(BaseModel):
    id: str
    equipment_id: str
    slot_date: date
    start_time: time
    end_time: time
    is_available: bool
    version: int


class ReservationCreate(BaseModel):
    equipment_id: str
    time_slot_id: str
    patient_id: str


class ReservationChangeSlot(BaseModel):
    new_time_slot_id: str
    version: int


class ReservationCancel(BaseModel):
    version: int


class ReservationCheckIn(BaseModel):
    version: int


class ReservationRelease(BaseModel):
    version: int


class ReservationOut(BaseModel):
    id: str
    equipment_id: str
    time_slot_id: str
    patient_id: str
    therapist_id: str
    status: ReservationStatus
    version: int
    created_at: datetime
    updated_at: datetime


class AuditLogOut(BaseModel):
    id: str
    reservation_id: Optional[str] = None
    maintenance_id: Optional[str] = None
    action: AuditAction
    operator_id: str
    operator_role: UserRole
    details: str
    created_at: datetime


class ConflictItem(BaseModel):
    type: str
    message: str
    related_ids: list[str] = []


class ConflictReport(BaseModel):
    conflicts: list[ConflictItem]


class DeviceMaintenanceCreate(BaseModel):
    equipment_id: str
    maintenance_type: MaintenanceType
    reason: str
    start_datetime: datetime
    end_datetime: datetime
    remark: str = ""


class DeviceMaintenanceUpdate(BaseModel):
    maintenance_type: Optional[MaintenanceType] = None
    reason: Optional[str] = None
    start_datetime: Optional[datetime] = None
    end_datetime: Optional[datetime] = None
    remark: Optional[str] = None
    status: Optional[MaintenanceStatus] = None
    version: int


class DeviceMaintenanceClose(BaseModel):
    version: int


class DeviceMaintenanceOut(BaseModel):
    id: str
    equipment_id: str
    maintenance_type: MaintenanceType
    reason: str
    start_datetime: datetime
    end_datetime: datetime
    status: MaintenanceStatus
    remark: str
    creator_id: str
    version: int
    created_at: datetime
    updated_at: datetime


class MaintenanceConflictReservation(BaseModel):
    reservation_id: str
    equipment_id: str
    patient_id: str
    therapist_id: str
    status: ReservationStatus
    slot_date: date
    start_time: time
    end_time: time
