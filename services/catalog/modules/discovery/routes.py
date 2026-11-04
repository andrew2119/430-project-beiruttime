from typing import Annotated, Literal
from fastapi import APIRouter, Path, Query, Request
from bt_contracts_core.errors import PublicError
from .models import AuctionRead, MAX_MINOR, SearchPage, WatchDetail
from .search import Filters, normalize
from .source_contract import PublicListing
from .dependencies import from_app
from . import service
from .upstream import read_auction

router=APIRouter(prefix='/v1/discovery/watches',tags=['public-discovery'])
canonical_router=APIRouter(tags=['public-catalog'])
Identifier=Annotated[str,Path(pattern=r'^[A-Za-z0-9_-]{1,100}$')]


def minor(value):
    if value is None:return None
    value=normalize(value)
    if not value.isascii()or not value.isdecimal()or len(value)>16 or int(value)>MAX_MINOR:
        raise PublicError('invalid_range','Enter integer minor units.',status=422)
    return int(value)


@router.get('',response_model=SearchPage)
async def find_watches(request:Request,q:str=Query('',max_length=160),brand:str=Query('',max_length=100),model:str=Query('',max_length=160),location:str=Query('',max_length=160),
    min_minor:str|None=Query(None,max_length=16),max_minor:str|None=Query(None,max_length=16),currency:Literal['USD','LBP']='USD',sale_mode:Literal['','fixed','auction','offer']='',
    sort:Literal['newest','price_asc','price_desc','ending_soon']='newest',cursor:str=Query('',max_length=1024),limit:int=Query(12,ge=1,le=24)):
    filters=Filters(q=q,brand=brand,model=model,location=location,min_minor=minor(min_minor),max_minor=minor(max_minor),currency=currency,sale_mode=sale_mode,sort=sort,limit=limit)
    return await service.find(request.app.state.pool,from_app(request.app,request.state.request_id),filters,cursor)


@router.get('/{identifier}',response_model=WatchDetail)
async def view_watch(identifier:Identifier,request:Request):
    return await service.view(request.app.state.pool,from_app(request.app,request.state.request_id),identifier)


@router.get('/{identifier}/auction',response_model=AuctionRead)
async def watch_auction(identifier:Identifier,request:Request):
    # Recheck public Catalog visibility, not an expensive/private detail composition.
    source=await service.raw_detail(request.app.state.pool,identifier)
    if source.facts.sale_mode!='auction':return AuctionRead(state='not_started')
    return await read_auction(getattr(request.app.state,'discovery_auction',None),str(source.id),request.state.request_id)


@canonical_router.get('/v1/listings/{identifier}',response_model=PublicListing)
async def canonical_listing(identifier:Identifier,request:Request):
    # This is publication/fact proof, NEVER current Orders availability or an
    # independent watch-authentication pass. Commands recheck their own authority.
    return await service.canonical(request.app.state.pool,from_app(request.app,request.state.request_id),identifier)
