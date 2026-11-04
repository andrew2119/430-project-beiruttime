"""Public Catalog keysets only; current stock/timing are joined over owning APIs."""
import base64
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Literal
from uuid import UUID
import asyncpg
from pydantic import ValidationError
from bt_contracts_core.errors import PublicError
from .models import MAX_MINOR
from .source_contract import COLUMNS, SOURCE, parse_row

SORTS = {'newest':'-extract(epoch FROM published_at)',
         'price_asc':"coalesce((facts->>'price_minor')::numeric,9000000000000001)",
         'price_desc':"coalesce(-(facts->>'price_minor')::numeric,9000000000000001)",
         'ending_soon':None}


def normalize(value: str) -> str:
    value=value.lower().translate(str.maketrans('أإآٱىة٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹','اااايه01234567890123456789'))
    return ' '.join(re.sub('[ـً-ٰٟ]','',value).split())


@dataclass(frozen=True)
class Filters:
    q: str = ''
    brand: str = ''
    model: str = ''
    location: str = ''
    min_minor: int | None = None
    max_minor: int | None = None
    currency: Literal['USD','LBP'] = 'USD'
    sale_mode: str = ''
    sort: str = 'newest'
    limit: int = 12

    def __post_init__(self):
        if self.sort not in SORTS or self.currency not in ('USD','LBP') or self.sale_mode not in ('','fixed','auction','offer') or not 1<=self.limit<=24:
            raise PublicError('invalid_filters','Check the search filters.',status=422)
        if len(self.q)>160 or len(self.q.split())>8 or len(self.brand)>100 or len(self.model)>160 or len(self.location)>160:
            raise PublicError('invalid_filters','Check the search filters.',status=422)
        if any(value is not None and (type(value)is not int or not 0<=value<=MAX_MINOR)for value in (self.min_minor,self.max_minor)):
            raise PublicError('invalid_range','Enter integer minor units.',status=422)
        if self.min_minor is not None and self.max_minor is not None and self.min_minor>self.max_minor:
            raise PublicError('invalid_range','Minimum price exceeds maximum price.',status=422,details={'field':'min_minor'})

    def fingerprint(self):
        values={key:normalize(value)if isinstance(value,str)else value for key,value in asdict(self).items()}
        return hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest()[:32]


def cursor_error():return PublicError('invalid_cursor','Return to the first search page.',status=422)


def encode_cursor(filters, key, identifier, window):
    raw=json.dumps({'v':1,'f':filters.fingerprint(),'k':key,'id':str(identifier),'w':window.isoformat()},separators=(',',':')).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip('=')


def decode_cursor(value, filters, now):
    try:
        if len(value)>1024 or not re.fullmatch('[A-Za-z0-9_-]+',value):raise ValueError()
        data=json.loads(base64.b64decode(value+'='*(-len(value)%4),altchars=b'-_',validate=True))
        if set(data)!={'v','f','k','id','w'} or data['v']!=1 or data['f']!=filters.fingerprint():raise ValueError()
        UUID(data['id'])
        if not isinstance(data['k'],str)or len(data['k'])>80:raise ValueError()
        position=Decimal(data['k'])
        if not position.is_finite()or abs(position)>Decimal('1e20'):raise ValueError()
        window=datetime.fromisoformat(data['w'])
        if window.tzinfo is None or window>now or(now-window).total_seconds()>86400:raise ValueError()
        return position,data['id'],window
    except(ValueError,TypeError,KeyError,InvalidOperation,OverflowError):raise cursor_error()from None


async def conditions(conn, filters, window):
    terms=set(normalize(' '.join((filters.q,filters.brand,filters.model,filters.location))).split())
    aliases=await conn.fetch('SELECT alias,canonical FROM catalog_discovery_aliases_v1 WHERE alias=ANY($1::text[])',list(terms))
    mapping={row['alias']:row['canonical']for row in aliases}
    alias=lambda value:' '.join(mapping.get(word,word)for word in normalize(value).split())
    args=[]
    def bind(value):args.append(value);return f'${len(args)}'
    clauses=[f'published_at<={bind(window)}',f"facts->>'currency'={bind(filters.currency)}"]
    norm=lambda value:f'catalog_discovery_canonicalize_v1({value})'
    for field in ('brand','model','location'):
        value=alias(getattr(filters,field))
        if value:
            expression="concat_ws(' ',facts->>'model',facts->>'reference')"if field=='model'else"facts->>'"+field+"'"
            clauses.append(f'strpos({norm(expression)},{bind(value)})>0')
    haystack=norm("concat_ws(' ',facts->>'brand',facts->>'model',facts->>'reference',facts->>'location',facts->>'condition')")
    for word in alias(filters.q).split():clauses.append(f'strpos({haystack},{bind(word)})>0')
    for value,operator in ((filters.min_minor,'>='),(filters.max_minor,'<=')):
        if value is not None:clauses.append(f"(facts->>'price_minor')::numeric{operator}{bind(Decimal(value))}")
    if filters.sale_mode:clauses.append(f"facts->>'sale_mode'={bind({'fixed':'fixed_price','auction':'auction','offer':'offer'}[filters.sale_mode])}")
    return clauses,args,bind


async def candidates(conn, filters, cursor=''):
    now=await conn.fetchval('SELECT clock_timestamp()')
    position,identifier,window=decode_cursor(cursor,filters,now)if cursor else(None,None,now)
    clauses,args,bind=await conditions(conn,filters,window)
    sort=SORTS[filters.sort]
    if sort is None:raise ValueError('Auction owns ending-soon order')
    if position is not None:clauses.append(f'({sort},id)>({bind(position)}::numeric,{bind(identifier)}::text::uuid)')
    budget=min(96,max(24,filters.limit*4+1))
    rows=await conn.fetch(f"SELECT {COLUMNS},({sort})::text AS position FROM {SOURCE} WHERE {' AND '.join(clauses)} ORDER BY {sort},id LIMIT {bind(budget+1)}",*args)
    result=[]
    for row in rows[:budget]:
        record=dict(row);key=record.pop('position');result.append((parse_row(record),key))
    return result,len(rows)>budget,window,now


async def by_ids(conn, filters, ids, window):
    if len(ids)>100:raise ValueError('Catalog candidate budget exceeded')
    clauses,args,bind=await conditions(conn,filters,window)
    token=bind(list(ids));clauses.append(f'id=ANY({token}::uuid[])')
    rows=await conn.fetch(f"SELECT {COLUMNS} FROM {SOURCE} WHERE {' AND '.join(clauses)}",*args)
    return {source.id:source for source in map(parse_row,rows)}


async def detail(conn, identifier):
    try:UUID(str(identifier))
    except(ValueError,TypeError):raise PublicError('not_found','Watch is not publicly available.',status=404)from None
    row=await conn.fetchrow(f'SELECT {COLUMNS} FROM {SOURCE} WHERE id=$1::text::uuid AND published_at<=clock_timestamp()',str(identifier))
    if row is None:raise PublicError('not_found','Watch is not publicly available.',status=404)
    source=parse_row(row)
    if source.id!=UUID(str(identifier)):raise ValueError('Invalid public listing binding')
    return source


UNAVAILABLE_SOURCE=(asyncpg.PostgresError,asyncpg.InterfaceError,ValidationError,ValueError)
