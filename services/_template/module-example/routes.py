from fastapi import APIRouter
router = APIRouter(prefix='/v1/example', tags=['example'])

@router.get('')
async def example():
    return {'state': 'unavailable', 'reason': 'Example module has no business implementation'}
