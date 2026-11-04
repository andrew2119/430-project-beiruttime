"""Opt-in sample content, published through the actual brand authorization path."""

import json
import os
from importlib.resources import files
from uuid import UUID
from bt_bulkheads import DependencyClient, Unavailable


async def seed(settings):
    brand = UUID(os.environ["BT_OPTIONS_SAMPLE_BRAND"])
    token = os.environ["BT_OPTIONS_BRAND_TOKEN"]
    source = json.loads(files("bt_contracts.catalog.options").joinpath("fixtures/options.v1.json").read_text())
    client = DependencyClient(
        "catalog-sample-import", os.getenv("CATALOG_API_URL", "http://catalog:8000"), timeout=4, concurrency=1
    )
    try:
        for option in source["options"]:
            response = await client.request(
                "PUT",
                f"/v1/brand-options/brands/{brand}/{option['kind']}/{option['id']}",
                headers={"Authorization": "Bearer " + token, "Idempotency-Key": f"sample-v1-{brand}-{option['id']}"},
                json=option["definition"],
            )
            if isinstance(response, Unavailable) or response.status_code != 200:
                raise RuntimeError("Sample option publication did not succeed")
    finally:
        await client.aclose()
