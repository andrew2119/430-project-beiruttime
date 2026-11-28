"""Deploy-applied photos for the seed's own drafts: one licensed repository photo each.

Each photo passes the same hash, byte, attribution and image normalization checks as the app's
demonstration upload, and is stored as that upload stores it (media row, variants, gallery, event).
A photo is attached only to a draft the seed's ownership record holds and nobody has touched yet
(revision 1, no photos), whose owner Identity's newest signed handoff, by Identity's order, still vouches for
while it is fresh (`handoff.admitted()`), and the media row, each variant and the event are entered in that
record. The attaching transaction checks that handoff under the holder's lock and keeps it through its write and
commit, so a withdrawal cannot arrive in between. Such a draft whose handoff does not vouch for its owner now is
counted by the reason and gets no photo.
A complete earlier run, or a draft its seller has already edited, is left as it is; a run after a
failed photo step attaches the photo it missed.
Photos are decoded in a worker thread outside any transaction, within the seed's time budget.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
from bt_runtime import demo_seed
from modules.listings.handoff import REASONS, admitted
from modules.listings.repository import emit
from .images import MAX_BYTES, attribution_matches, embed_attribution, normalize

# The repository's illustrative photo for each seed watch (the same pairing as its DEMO-WATCH fixtures).
PHOTOS = {"auction": "IMG-03", "buy-now": "IMG-01", "spare": "IMG-02"}
UNTOUCHED = """SELECT * FROM catalog_listings WHERE id=$1 AND demo_key=$2 AND is_demo AND status='draft'
    AND revision=1 AND cardinality(photo_ids)=0"""


def photo(root: Path, assets: dict, asset_id: str):
    asset = assets[asset_id]
    content = (root / "watches" / Path(asset["file"]).name).read_bytes()
    if len(content) > MAX_BYTES or hashlib.sha256(content).hexdigest() != asset["local_sha256"]:
        raise ValueError("Seed photo hash or byte limit")
    if not asset.get("license_url") or not attribution_matches(content, asset):
        raise ValueError("Seed photo attribution")
    variants = normalize(content)
    embed_attribution(variants, asset)
    return content, variants


def prepare(items):
    root = Path(os.getenv("BT_DEMO_ROOT", "/app/demo"))
    assets = {asset["id"]: asset for asset in json.loads((root / "images-manifest.json").read_text())["assets"]}
    return assets, {item: photo(root, assets, PHOTOS[item]) for item in items}


async def needs_photo(tx, listing, lock=False) -> str | None:
    """'attach' for the seed's own untouched draft whose owner Identity's newest handoff vouches for now, the
    reason (handoff.REASONS) for such a draft whose handoff does not, else None. The holder's lock it takes is
    kept until the caller's transaction ends."""
    if not await demo_seed.owned(tx, "catalog_listings", {"id": listing.id}, listing.key):
        return None
    if not await tx.fetchrow(UNTOUCHED + (" FOR UPDATE SKIP LOCKED" if lock else ""), listing.id, listing.key):
        return None
    return await admitted(tx, listing.sample_set, demo_seed.HOLDERS[listing.seller]) or "attach"


async def apply(settings):
    if not demo_seed.enabled():
        return {"skipped": "switch"}
    counts, pending = {"attached": 0, "unchanged": 0, **dict.fromkeys(REASONS, 0)}, []
    async with demo_seed.transaction(settings.database_url, "catalog-media") as tx:
        for listing in demo_seed.listings():
            need = await needs_photo(tx, listing)
            if need == "attach":
                pending.append(listing)
            else:
                counts[need or "unchanged"] += 1
    if not pending:
        return counts
    # Decoded in the loop's executor, outside any transaction, so no lock is held meanwhile and the seed's
    # total budget still bounds it.
    assets, prepared = await asyncio.get_running_loop().run_in_executor(
        None, prepare, sorted({entry.item for entry in pending}))
    async with demo_seed.transaction(settings.database_url, "catalog-media") as tx:
        for listing in pending:
            need = await needs_photo(tx, listing, lock=True)
            if need != "attach":
                counts[need or "unchanged"] += 1
                continue
            content, variants = prepared[listing.item]
            detail = variants["detail"]
            media = await tx.fetchval(
                """INSERT INTO catalog_media(id,listing_id,kind,content_hash,source_bytes,mime,width,height,credit,
                private_bytes) VALUES($1,$2,'public_photo',$3,$4,'image/jpeg',$5,$6,$7::jsonb,NULL)
                ON CONFLICT DO NOTHING RETURNING id""",
                listing.photo_id,
                listing.id,
                hashlib.sha256(content).hexdigest(),
                len(content),
                detail["width"],
                detail["height"],
                json.dumps(assets[PHOTOS[listing.item]]),
            )
            if media is None:
                demo_seed.report("catalog-media", f"foreign {listing.key}: pinned photo id already in use")
                counts["unchanged"] += 1
                continue
            await demo_seed.record(tx, listing.key, "catalog_media", {"id": media})
            for name, value in variants.items():
                await tx.execute(
                    "INSERT INTO catalog_media_variants(media_id,variant,width,height,content) VALUES($1,$2,$3,$4,$5)",
                    media, name, value["width"], value["height"], value["content"])
                await demo_seed.record(tx, listing.key, "catalog_media_variants", {"media_id": media, "variant": name})
            row = await tx.fetchrow(
                """UPDATE catalog_listings SET photo_ids=array_append(photo_ids,$2),cover_id=coalesce(cover_id,$2),
                revision=revision+1,updated_at=now() WHERE id=$1 RETURNING *""",
                listing.id,
                media,
            )
            async with demo_seed.events(tx, listing.key):
                await emit(tx, demo_seed.REQUEST, row, "media-updated")
            counts["attached"] += 1
    return counts
