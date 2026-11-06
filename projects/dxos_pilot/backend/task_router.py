"""API 路由：任务提交 / 查询 / 取消。

职责：HTTP DTO 转换 + 调用应用层用例。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from scheduling import build_cancel_use_case, build_submit_use_case
from scheduling.domain.entities import TaskNotFoundError
from scheduling.infrastructure.sqlite_task_repository import SqliteTaskRepository

router = APIRouter(prefix="/tasks", tags=["tasks"])


class TaskSubmit(BaseModel):
    tenant_id: str
    model_name: str
    vram_mb: int | None = None
    priority: int = 0


@router.post("/submit", status_code=201)
def submit_task(body: TaskSubmit) -> dict:
    uc = build_submit_use_case()
    try:
        task = uc.execute(body.tenant_id, body.model_name, body.vram_mb, body.priority)
    except Exception as e:
        _raise_mapped(e)
    return _task_to_dict(task)


@router.get("")
def list_tasks(tenant_id: str | None = None) -> list[dict]:
    repo = SqliteTaskRepository()
    if tenant_id:
        tasks = repo.list_by_tenant(tenant_id)
    else:
        tasks = repo.list_all()
    return [_task_to_dict(t) for t in tasks]


@router.get("/{task_id}")
def get_task(task_id: str) -> dict:
    repo = SqliteTaskRepository()
    task = repo.get(task_id)
    if task is None:
        raise HTTPException(404, f"任务 {task_id} 不存在")
    return _task_to_dict(task)


@router.post("/{task_id}/cancel")
def cancel_task(task_id: str) -> dict:
    uc = build_cancel_use_case()
    try:
        task = uc.execute(task_id)
    except TaskNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(409, str(e))
    except Exception as e:
        _raise_mapped(e)
    return _task_to_dict(task)


def _task_to_dict(t) -> dict:
    return {
        "task_id": t.task_id,
        "tenant_id": t.tenant_id,
        "model_name": t.model_name,
        "status": t.status.value,
        "gpu_index": t.gpu_index,
        "vram_mb": t.vram_mb,
        "priority": t.priority,
        "created_at": t.created_at.isoformat(),
        "started_at": t.started_at.isoformat() if t.started_at else None,
        "finished_at": t.finished_at.isoformat() if t.finished_at else None,
    }


def _raise_mapped(e: Exception) -> None:
    from scheduling.domain.entities import (
        IllegalStateTransitionError,
        InsufficientQuotaError,
        ModelNotFoundError,
        TenantNotFoundError,
    )
    if isinstance(e, InsufficientQuotaError):
        raise HTTPException(409, str(e))
    if isinstance(e, IllegalStateTransitionError):
        raise HTTPException(409, str(e))
    if isinstance(e, TenantNotFoundError):
        raise HTTPException(404, str(e))
    if isinstance(e, ModelNotFoundError):
        raise HTTPException(404, str(e))
    if isinstance(e, ValueError):
        raise HTTPException(400, str(e))
    raise HTTPException(500, str(e))
