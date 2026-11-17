"""Deterministic public alternatives; no private records or behavioral inputs."""
import asyncio
import importlib.util
from pathlib import Path
import unicodedata

_contract = Path(__file__).resolve().parents[4] / 'packages/contracts-catalog/similar-watches/current.py'
_spec = importlib.util.spec_from_file_location('similar_watch_contract', _contract)
contract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(contract)
Query, Watch, Match, Result = contract.Query, contract.Watch, contract.Match, contract.Result


def normalized(value):
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())


def matching(source, candidate):
    brand = normalized(source.brand) == normalized(candidate.brand)
    if brand and normalized(source.reference) and normalized(source.reference) == normalized(candidate.reference):
        return 'reference'
    if brand:
        return 'brand'
    if source.price_minor is not None and candidate.price_minor is not None:
        if source.price_minor * 80 <= candidate.price_minor * 100 <= source.price_minor * 120:
            return 'price_band'
    return None


async def find(provider, query):
    """Provider returns one complete, current public set including the source."""
    base = dict(operation_id=query.operation_id, subject_id=query.subject_id,
                expected_revision=query.expected_revision, offset=query.offset)
    try:
        async with asyncio.timeout(1):
            records = await provider.current_public()
            if len(records) > 1001:
                raise ValueError('Public set exceeds the complete-read budget')
            watches = [Watch.model_validate(row) for row in records]
            if len({row.id for row in watches}) != len(watches):
                raise ValueError('Duplicate public listing')
            source = next((row for row in watches if row.id == query.subject_id), None)
            if source is None:
                return Result(**base, state='denied')
            base.update(watch_id=source.watch_id, revision=source.revision)
            if source.revision != query.expected_revision:
                return Result(**base, state='stale')
            found = []
            for row in watches:
                if not row.available or row.watch_id == source.watch_id:
                    continue
                rule = matching(source, row)
                if rule:
                    distance = abs(row.price_minor - source.price_minor) if row.price_minor is not None and source.price_minor is not None else contract.MAX_MINOR + 1
                    found.append((('reference', 'brand', 'price_band').index(rule), distance, str(row.id), row, rule))
            found.sort(key=lambda row: row[:3])
            unique = {}
            for row in found:
                unique.setdefault(row[3].watch_id, row)
            ordered = list(unique.values())
            total = len(ordered)
            items = tuple(Match(watch=row[3], rule=row[4]) for row in ordered[query.offset:query.offset + 20])
            return Result(**base, state='ready' if total else 'empty', items=items, total=total,
                          next_offset=query.offset + 20 if query.offset + 20 < total else None)
    except (TimeoutError, OSError, ValueError, TypeError):
        return Result(**base, state='unavailable', pending_reason='current_source_unavailable')
