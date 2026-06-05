from fastapi import FastAPI
from app.routes.auth import router as auth_router
from app.routes.equipment import router as equipment_router
from app.routes.reservation import router as reservation_router
from app.routes.audit import router as audit_router

app = FastAPI(
    title="康复科室训练设备预约管理系统",
    description="管理训练设备的预约、签到、占用和释放，支持乐观锁防并发",
    version="1.0.0",
)

app.include_router(auth_router)
app.include_router(equipment_router)
app.include_router(reservation_router)
app.include_router(audit_router)


@app.get("/health")
def health():
    return {"status": "ok"}
