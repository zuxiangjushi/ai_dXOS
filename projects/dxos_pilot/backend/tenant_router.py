"""API 路由：租户管理。

职责：HTTP DTO ↔ 领域对象转换 + 调用应用层用例。
不包含业务逻辑；所有业务规则在 scheduling/application 和 scheduling/domain 中。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from scheduling import build_tenant_use_cases
from scheduling.domain.entities import TenantNotFoundError

router = APIRouter(prefix="/tenants", tags=["tenants"])


class TenantCreate(BaseModel):
    tenant_id: str
    name: str
    status: str = "active"


class TenantStatusUpdate(BaseModel):
    status: str


@router.post("", status_code=201)
def create_tenant(body: TenantCreate) -> dict:
    create_uc, _, _ = build_tenant_use_cases()
    try:
        tenant = create_uc.execute(body.tenant_id, body.name, body.status)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {
        "tenant_id": tenant.tenant_id,
        "name": tenant.name,
        "status": tenant.status,
        "created_at": tenant.created_at.isoformat(),
    }


@router.get("")
def list_tenants() -> list[dict]:
    from scheduling.infrastructure.sqlite_tenant_repository import SqliteTenantRepository
    repo = SqliteTenantRepository()
    tenants = repo.list_all()
    return [
        {
            "tenant_id": t.tenant_id,
            "name": t.name,
            "status": t.status,
            "created_at": t.created_at.isoformat(),
        }
        for t in tenants
    ]


@router.get("/{tenant_id}")
def get_tenant(tenant_id: str) -> dict:
    from scheduling.infrastructure.sqlite_tenant_repository import SqliteTenantRepository
    repo = SqliteTenantRepository()
    t = repo.get(tenant_id)
    if t is None:
        raise HTTPException(404, f"租户 {tenant_id} 不存在")
    return {
        "tenant_id": t.tenant_id,
        "name": t.name,
        "status": t.status,
        "created_at": t.created_at.isoformat(),
    }


@router.patch("/{tenant_id}/status")
def update_tenant_status(tenant_id: str, body: TenantStatusUpdate) -> dict:
    _, update_uc, _ = build_tenant_use_cases()
    try:
        tenant = update_uc.execute(tenant_id, body.status)
    except TenantNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"tenant_id": tenant.tenant_id, "status": tenant.status}


@router.delete("/{tenant_id}", status_code=200)
def delete_tenant(tenant_id: str) -> dict:
    _, _, delete_uc = build_tenant_use_cases()
    try:
        delete_uc.execute(tenant_id)
    except TenantNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(409, str(e))
    return {"detail": f"租户 {tenant_id} 已删除"}
