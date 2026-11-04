"""Offline provenance and decoded local-asset proof; performs no network request."""

import hashlib
import json
from pathlib import Path
from PIL import Image

root = Path(__file__).resolve().parents[3]
manifest = json.loads((root / "demo/images-manifest.json").read_text())
fixtures = json.loads((root / "demo/listings.json").read_text())
assert len(manifest["assets"]) == 3 and len(fixtures["listings"]) == 6
for asset in manifest["assets"]:
    for field in ("author", "source_url", "license", "license_url", "source_sha256", "local_sha256"):
        assert asset.get(field), (asset["id"], field)
    path = root / asset["planned_local_path"]
    content = path.read_bytes()
    assert len(content) == asset["local_bytes"] < 8_000_000
    assert hashlib.sha256(content).hexdigest() == asset["local_sha256"]
    assert asset["author"].encode() in content and asset["license_url"].encode() in content
    assert ("License name: " + asset["license"] + "\n").encode() in content
    with Image.open(path) as image:
        image.load()
        assert image.width * image.height <= 20_000_000
        assert max(image.size) <= 1600 and list(image.size) == asset["local_dimensions"]
        assert not image.getexif()
    print(asset["id"], asset["license"], asset["local_sha256"])
for listing in fixtures["listings"]:
    assert listing["is_demo"]
    assert listing["payment_status"] is None and listing["inspection_result"] is None
    assert all(image in {asset["id"] for asset in manifest["assets"]} for image in listing["image_ids"])
print("Three licensed local assets and six illustrative fixture records verified.")
