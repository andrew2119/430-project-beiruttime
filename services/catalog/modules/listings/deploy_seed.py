"""Deploy-applied sample drafts: each set's private seller's auction watch, and its sample business's
Buy Now watch and a spare listing for the report step, owned by that business's sample staff.

Drafts only, written as the app's own draft save writes them (row and draft-saved event), and each row
and event is entered in the seed's ownership record. Nothing is published, quoted, reserved or auctioned
here, so no auction window exists to move. Publishing stays a person's click in the app, with every
publication check the app runs. A pinned id, demo key or watch id held by a row the seed did not insert
is logged as foreign and never touched.
A draft is admitted only while Identity's newest signed handoff for that set's seller, or for its staff and
their business, by Identity's order, verifies, is ready, fresh and names exactly the owner account and business
the draft gets (`handoff.admitted()`), checked under that holder's lock, which this step's transaction keeps
through its write and commit: with none yet it waits, one Identity withdrew or one too old waits for a later
deploy, and a newest one that is missing, fails its check or names anything else refuses it; an older handoff
never stands in. While a handoff for that holder is arriving the draft is skipped as busy.
"""
from bt_contracts.catalog.listings.v1 import WatchFacts, incomplete
from bt_runtime import demo_seed
from .handoff import REASONS, admitted
from .repository import emit

CONDITION = "Sample description for the demonstration; the photo is illustrative, not evidence of this watch."
# Same brand, model, sale mode and price as the repository's DEMO-WATCH-05, -02 and -04 fixtures.
WATCHES = {
    "auction": ("Seiko", "5 Automatic", "DEMO-WATCH-05", "auction", 22000),
    "buy-now": ("Seiko", "5 Automatic", "DEMO-WATCH-02", "fixed_price", 18000),
    "spare": ("Omega", "X33 Mk1", "DEMO-WATCH-04", "fixed_price", 210000),
}
LOCATIONS = {"private": "Achrafieh, Beirut", "dealer": "Hamra, Beirut"}
PRIVATE_LABEL = "Demonstration private seller"
# One log line for each refusal a person can act on; a handoff not yet received is only counted.
REFUSALS = {
    "busy": "busy {key}: an Identity handoff for its holder is arriving",
    "unkeyed": "refused {key}: BT_DEMO_SEED_HANDOFF_PUBLIC_KEY is missing or wrongly set",
    "invalid": "refused {key}: the newest Identity handoff is missing or fails its check",
    "mismatched": "refused {key}: the Identity handoff differs",
    "withdrawn": "waiting {key}: Identity withdrew its handoff",
    "stale": "waiting {key}: the Identity handoff is not fresh; deploy Identity, then Catalog",
}


def label(listing) -> str:
    # The labels the app's own draft save writes for a demo private draft and a sample business's draft.
    if listing.seller == "private":
        return PRIVATE_LABEL
    return "Demonstration " + demo_seed.business(listing.sample_set).public_name


def seller(listing):
    """Owner account and business of a seed draft: the set's private seller, or its sample staff and business,
    exactly as Identity's handoff for that holder names them."""
    return demo_seed.handoff_ids(listing.sample_set, demo_seed.HOLDERS[listing.seller])


def facts(listing) -> WatchFacts:
    brand, model, reference, sale_mode, price = WATCHES[listing.item]
    value = WatchFacts(
        brand=brand,
        model=model,
        reference=reference,
        year=2020,
        condition=CONDITION,
        component_wear={"case": "Sample condition; the photo is illustrative only."},
        location=LOCATIONS[listing.seller],
        included=[],
        no_documents=True,
        modified=False,
        modifications=[],
        ownership_confirmed=True,
        sale_mode=sale_mode,
        currency="USD",
        price_minor=price,
    )
    # Complete once its one photo is attached, so Publish is the only step left for the seller.
    if incomplete(value, 1):
        raise ValueError("Seed watch facts are incomplete")
    return value


async def apply(settings):
    if not demo_seed.enabled():
        return {"skipped": "switch"}
    counts = {"created": 0, "kept": 0, "foreign": 0, **dict.fromkeys(REASONS, 0)}
    async with demo_seed.transaction(settings.database_url, "catalog-listings") as tx:
        for listing in demo_seed.listings():
            if await demo_seed.owned(tx, "catalog_listings", {"id": listing.id}, listing.key):
                counts["kept"] += 1
                continue
            refusal = await admitted(tx, listing.sample_set, demo_seed.HOLDERS[listing.seller])
            if refusal is not None:
                if refusal in REFUSALS:
                    demo_seed.report("catalog-listings", REFUSALS[refusal].format(key=listing.key))
                counts[refusal] += 1
                continue
            owner, organization = seller(listing)
            row = await tx.fetchrow(
                """INSERT INTO catalog_listings(id,owner_subject_id,organization_id,seller_type,seller_label,
                physical_watch_id,facts,is_demo,demo_key) VALUES($1,$2,$3,$4,$5,$6,$7::jsonb,true,$8)
                ON CONFLICT DO NOTHING RETURNING *""",
                listing.id,
                owner,
                organization,
                listing.seller,
                label(listing),
                listing.watch_id,
                facts(listing).model_dump_json(),
                listing.key,
            )
            if row is None:
                demo_seed.report("catalog-listings", f"foreign {listing.key}: pinned id, key or watch already in use")
                counts["foreign"] += 1
                continue
            await demo_seed.record(tx, listing.key, "catalog_listings", {"id": row["id"]})
            async with demo_seed.events(tx, listing.key):
                await emit(tx, demo_seed.REQUEST, row, "draft-saved")
            counts["created"] += 1
    return counts
