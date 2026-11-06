"""用例：租户管理（创建 / 改状态 / 删除）。"""
from __future__ import annotations

from ..domain.entities import Tenant, TenantNotFoundError
from .ports import TenantRepository


class CreateTenantUseCase:
    """创建新租户。"""

    def __init__(self, tenant_repo: TenantRepository):
        self._tenants = tenant_repo

    def execute(self, tenant_id: str, name: str, status: str = "active") -> Tenant:
        tenant = Tenant(tenant_id=tenant_id, name=name, status=status)
        self._tenants.create(tenant)
        return tenant


class UpdateTenantStatusUseCase:
    """修改租户状态（active / disabled）。"""

    def __init__(self, tenant_repo: TenantRepository):
        self._tenants = tenant_repo

    def execute(self, tenant_id: str, status: str) -> Tenant:
        tenant = self._tenants.get(tenant_id)
        if tenant is None:
            raise TenantNotFoundError(f"租户 {tenant_id} 不存在")
        self._tenants.update_status(tenant_id, status)
        tenant.status = status
        return tenant


class DeleteTenantUseCase:
    """删除租户（前置条件：无活跃任务、无未释放预扣）。"""

    def __init__(self, tenant_repo: TenantRepository):
        self._tenants = tenant_repo

    def execute(self, tenant_id: str) -> None:
        tenant = self._tenants.get(tenant_id)
        if tenant is None:
            raise TenantNotFoundError(f"租户 {tenant_id} 不存在")
        active_tasks = self._tenants.count_active_tasks(tenant_id)
        active_res = self._tenants.count_active_reservations(tenant_id)
        if active_tasks > 0 or active_res > 0:
            raise ValueError(
                f"租户 {tenant_id} 仍有 {active_tasks} 个活跃任务 / {active_res} 个未释放预扣，不能删除"
            )
        self._tenants.delete(tenant_id)
