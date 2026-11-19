"""Additive route factory; composition supplies current scoped providers."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from uuid import UUID
from fastapi import APIRouter, Header, Query

_spec = spec_from_file_location('seller_follows_contract', Path(__file__).resolve().parents[4] / 'packages/contracts-comms/seller-follows/schema.py')
_contract = module_from_spec(_spec)
_spec.loader.exec_module(_contract)
Command = _contract.Command
NoticeCommand = _contract.NoticeCommand


def create_router(store):
    router = APIRouter(prefix='/v1/seller-follows')

    @router.get('')
    async def page(page: int = Query(0, ge=0, le=20000), authorization: str = Header()):
        return await store.page(authorization, page)

    @router.get('/sellers/{seller_id}')
    async def status(seller_id: UUID, authorization: str = Header()):
        return await store.status(authorization, seller_id)

    @router.put('')
    async def change(command: Command, authorization: str = Header()):
        return await store.command(authorization, command)

    @router.get('/operations/{operation_id}')
    async def operation(operation_id: UUID, authorization: str = Header()):
        return await store.operation(authorization, operation_id)

    @router.get('/notices')
    async def notices(page: int = Query(0, ge=0, le=20000), authorization: str = Header()):
        return await store.notices(authorization, page)

    @router.get('/notices/{notice_id}/destination')
    async def destination(notice_id: UUID, authorization: str = Header()):
        return await store.destination(authorization, notice_id)

    @router.put('/notices')
    async def notice_change(command: NoticeCommand, authorization: str = Header()):
        return await store.notice_command(authorization, command)

    return router
