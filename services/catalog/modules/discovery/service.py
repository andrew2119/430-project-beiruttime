"""Compose current public reads without inventing stock, assurance or auction time."""
import asyncio
from dataclasses import dataclass
from bt_contracts_core.errors import PublicError
from . import search as repository
from .dependencies import Reads
from .models import Assurance, HistoryPage, Photo, SearchPage, Seller, WatchDetail, WatchSummary
from .upstream import money


def unavailable():return PublicError('unavailable','Current marketplace information is unavailable.',status=503)


def business_eligible(business):
    return business is not None and business.state == 'active' and business.platform_onboarded and business.authenticated_business and 'sales' in business.capabilities


@dataclass
class Resolved:
    source: object
    availability: object
    business: object
    timing: object
    timing_known: bool

    @property
    def authority_known(self):
        return self.availability is not None and(self.source.seller_type=='private'or self.business is not None)and self.timing_known

    @property
    def state(self):
        if not self.authority_known:return 'unavailable'
        if self.source.seller_type != 'private' and not business_eligible(self.business):return 'unavailable'
        if self.availability.status=='reserved':return 'reserved'
        if self.source.facts.sale_mode=='auction':
            if self.timing is None:return 'not_started'
            if self.availability.status!='fenced':return 'unavailable'
            return 'ended'if self.timing.status=='ended'else 'available'
        return 'available'if self.availability.status=='available'else 'unavailable'


async def resolve(sources, reads: Reads, timings, missing, business_cache):
    async def one(source):
        business_task=None
        if source.organization_id is not None:
            key=(source.organization_id,source.seller_type)
            if key not in business_cache:business_cache[key]=asyncio.create_task(reads.business(source))
            business_task=business_cache[key]
        availability_task=asyncio.create_task(reads.availability(source))
        if business_task:availability,business=await asyncio.gather(availability_task,business_task)
        else:availability,business=await availability_task,None
        needs_timing=source.facts.sale_mode=='auction'
        known=not needs_timing or(timings is not None and(source.id in timings or source.id in missing))
        return Resolved(source,availability,business,timings.get(source.id)if timings else None,known)
    return await asyncio.gather(*(one(source)for source in sources))


def title(source):return f'{source.facts.brand} {source.facts.model}'.strip()


def photo(source, asset, variant, credit=None):
    caption=None
    if credit:
        caption=' · '.join(part for part in (credit.credit,credit.source_url,credit.license,credit.license_url,credit.changes)if part)
    return Photo(id=str(asset),url=f'/api/web/v1/catalog/v1/listings/{source.id}/photos/{asset}/{variant}',alt=(credit.alt_en if credit and credit.alt_en else title(source)),alt_ar=(credit.alt_ar if credit and credit.alt_ar else title(source)),credit=caption)


def summary(result):
    source=result.source
    return WatchSummary(id=str(source.id),revision=source.revision,title=title(source),brand=source.facts.brand,model=source.facts.model,location=source.facts.location,
        price=money(source.facts.price_minor,source.facts.currency)if source.facts.price_minor is not None else None,
        sale_mode={'fixed_price':'fixed','auction':'auction','offer':'offer'}[source.facts.sale_mode],sale_state=result.state,
        thumbnail=photo(source,source.cover_id,'thumb'),published_at=source.published_at,
        ends_at=result.timing.current_ends_at if result.timing else None,demo=source.is_demo)


async def _read_candidates(pool, filters, cursor):
    async with pool.acquire(timeout=.2)as conn:return await repository.candidates(conn,filters,cursor)


async def find(pool, reads, filters, cursor=''):
    try:
        async with asyncio.timeout(.95):
            page = await _ending_search(pool,reads,filters,cursor)if filters.sort=='ending_soon'else await _catalog_search(pool,reads,filters,cursor)
            try:
                async with asyncio.timeout(.15):page.total = await reads.search_total(filters,page.server_time)
            except (TimeoutError,OSError):pass
            return page
    except(TimeoutError,OSError,*repository.UNAVAILABLE_SOURCE):raise unavailable()from None


async def _catalog_search(pool, reads, filters, cursor):
    candidates,more,window,now=await _read_candidates(pool,filters,cursor)
    ids=[source.id for source,_ in candidates if source.facts.sale_mode=='auction']
    timings,missing=await reads.timing_batch(ids)
    cache={};found=[];last_scanned=None
    for start in range(0,len(candidates),4):
        batch=candidates[start:start+4]
        resolved=await resolve([source for source,_ in batch],reads,timings,missing,cache)
        for result,(_,position)in zip(resolved,batch):
            if not result.authority_known:raise unavailable()
            last_scanned=(result.source,position)
            if result.state=='available':found.append((summary(result),position))
            if len(found)>filters.limit:break
        if len(found)>filters.limit:break
    has_more=len(found)>filters.limit or more
    items=[item for item,_ in found[:filters.limit]]
    if not items and more:raise PublicError('search_window_unavailable','Refine the search and try again.',status=503)
    if len(found)>filters.limit:
        last,key=found[filters.limit-1];identifier=last.id
    elif last_scanned:
        source,key=last_scanned;identifier=str(source.id)
    else:key,identifier='0',None
    next_cursor=repository.encode_cursor(filters,key,identifier,window)if has_more and identifier else None
    return SearchPage(items=items,next_cursor=next_cursor,server_time=now)


async def _ending_search(pool, reads, filters, cursor):
    async with pool.acquire(timeout=.2)as conn:now=await conn.fetchval('SELECT clock_timestamp()')
    _,provider_cursor,window=repository.decode_cursor(cursor,filters,now)if cursor else(None,None,now)
    found=[];seen=set();cache={};last_scanned=None;more=False
    for _ in range(3):
        page=await reads.endings(provider_cursor,100)
        if page is None:raise unavailable()
        ids=[item.listing_id for item in page.items]
        if len(set(ids))!=len(ids):raise unavailable()
        async with pool.acquire(timeout=.2)as conn:rows=await repository.by_ids(conn,filters,ids,window)
        matching=[(item,rows[item.listing_id])for item in page.items if item.auction_id not in seen and item.listing_id in rows and rows[item.listing_id].facts.sale_mode=='auction']
        for start in range(0,len(matching),4):
            batch=matching[start:start+4]
            timing_map={item.listing_id:item for item,_ in batch}
            resolved=await resolve([source for _,source in batch],reads,timing_map,set(),cache)
            for result,(timing,_)in zip(resolved,batch):
                if not result.authority_known:raise unavailable()
                seen.add(timing.auction_id);last_scanned=timing.auction_id
                if result.state=='available':found.append((summary(result),timing.auction_id))
                if len(found)>filters.limit:break
            if len(found)>filters.limit:break
        more=page.next_cursor is not None
        if len(found)>filters.limit:break
        if not more:break
        provider_cursor=page.next_cursor
    items=[item for item,_ in found[:filters.limit]]
    if not items and more:raise PublicError('search_window_unavailable','Refine the search and try again.',status=503)
    identifier=found[filters.limit-1][1]if len(found)>filters.limit else(provider_cursor if more else last_scanned)
    next_cursor=repository.encode_cursor(filters,'0',identifier,window)if(len(found)>filters.limit or more)and identifier else None
    return SearchPage(items=items,next_cursor=next_cursor,server_time=now)


async def raw_detail(pool, identifier):
    try:
        async with pool.acquire(timeout=.2)as conn:return await repository.detail(conn,identifier)
    except(TimeoutError,OSError,*repository.UNAVAILABLE_SOURCE):raise unavailable()from None


async def canonical(pool, reads, identifier):
    source=await raw_detail(pool,identifier)
    if source.organization_id is not None:
        try:
            async with asyncio.timeout(.5):business=await reads.business(source)
        except TimeoutError:raise unavailable()from None
        if business is None:raise unavailable()
        if not business_eligible(business):
            raise PublicError('listing_ineligible','This business cannot currently offer this listing.',status=403)
    return source


async def view(pool, reads, identifier):
    source=await raw_detail(pool,identifier)
    try:
        async with asyncio.timeout(.85):
            (timings,missing),credits=await asyncio.gather(reads.timing_batch([source.id])if source.facts.sale_mode=='auction'else _no_timing(),reads.credits(source))
            result=(await resolve([source],reads,timings,missing,{}))[0]
            public_facts = await reads.public_facts(source) if source.organization_id is None or business_eligible(result.business) else None
    except(TimeoutError,OSError):
        result=Resolved(source,None,None,None,False);credits=None;public_facts=None
    base=summary(result).model_dump()
    if credits is None:base['thumbnail']=None
    facts=source.facts
    parts=[f'{item.component} · {item.provenance} · {item.modifier} · {item.warranty_issuer}'+(f' · {item.notes}'if item.notes else '')for item in facts.modifications]
    official=source.seller_type!='private'
    verified=official and result.business is not None and result.business.state=='active'and result.business.platform_onboarded and result.business.authenticated_business
    return WatchDetail(**base,history_next_cursor=public_facts.history_next_cursor if public_facts else None,history_revision=public_facts.revision if public_facts else None,no_documents=facts.no_documents,history=public_facts.history if public_facts else None,reference=facts.reference or None,year=facts.year,component_wear=facts.component_wear,description='',condition=facts.condition,
        included_items=facts.included,modified=facts.modified,modified_parts=parts,
        photos=[photo(source,asset,'detail',credits[asset])for asset in source.photo_ids]if credits is not None else [],media_state='available'if credits is not None else'unavailable',
        seller=Seller(id=str(source.seller_id),city=public_facts.city if public_facts else None,display_name=result.business.public_name if result.business else source.seller_label,kind=source.seller_type,completed_sales=public_facts.released_sales if public_facts else None,joined_at=public_facts.joined_at if public_facts else None,review_distribution=public_facts.review_distribution if public_facts else None),
        assurance=Assurance(kind='official_business'if official else'private_inspection',status=('onboarded'if verified else'unavailable')if official else(public_facts.inspection if public_facts and public_facts.inspection else'unavailable')))


async def _no_timing():return {},set()


async def history(pool, reads, identifier, cursor, listing_revision, revision):
    source = await canonical(pool, reads, identifier)
    if source.revision != listing_revision:
        raise PublicError('stale_revision', 'The listing changed. Reload the watch history.', status=409)
    try:
        async with asyncio.timeout(.5):
            facts = await reads.public_facts(source, cursor, revision)
    except (TimeoutError, OSError):
        raise unavailable() from None
    if facts is None:raise unavailable()
    return HistoryPage(history=facts.history, next_cursor=facts.history_next_cursor,
        revision=facts.revision, listing_revision=source.revision)
