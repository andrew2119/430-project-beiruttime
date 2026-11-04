"""Download only the three approved openly licensed Commons originals."""

import hashlib
import io
import json
import time
from pathlib import Path
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.parse import urlparse
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[4]
MANIFEST = ROOT / "demo/images-manifest.json"


class ApprovedRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        count = getattr(req, "redirect_count", 0) + 1
        if count > 3 or urlparse(newurl).hostname != "upload.wikimedia.org" or urlparse(newurl).scheme != "https":
            raise ValueError("Unapproved image redirect")
        result = super().redirect_request(req, fp, code, msg, headers, newurl)
        result.redirect_count = count
        return result


def attributed(content, asset):
    text = (
        "Author: "
        + asset["author"]
        + "\n"
        + asset["credit"]
        + "\nSource: "
        + asset["source_url"]
        + "\nLicense: "
        + asset["license_url"]
        + "\nLicense name: "
        + asset["license"]
        + "\nChanges: oriented, metadata removed, resized and re-encoded."
    ).encode("utf-8")
    if not content.startswith(b"\xff\xd8") or text in content:
        return content
    return content[:2] + b"\xff\xfe" + (len(text) + 2).to_bytes(2, "big") + text + content[2:]


def main():
    manifest = json.loads(MANIFEST.read_text())
    opener = build_opener(ApprovedRedirects())
    for asset in manifest["assets"]:
        existing = ROOT / asset["planned_local_path"]
        if (
            existing.exists()
            and asset.get("source_sha256")
            and hashlib.sha256(existing.read_bytes()).hexdigest() == asset.get("local_sha256")
        ):
            local = attributed(existing.read_bytes(), asset)
            existing.write_bytes(local)
            asset.update(
                local_sha256=hashlib.sha256(local).hexdigest(),
                local_bytes=len(local),
                attribution_metadata="Authored JPEG comment: author, source, license and changes; source metadata removed.",
            )
            MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
            continue
        if not all(asset.get(k) for k in ("author", "license", "license_url", "source_url")):
            raise ValueError(f"{asset['id']}: missing license")
        url = asset["download_url"]
        if urlparse(url).hostname != "upload.wikimedia.org" or not url.startswith("https://"):
            raise ValueError(f"{asset['id']}: invalid source")
        with opener.open(
            Request(
                url,
                headers={
                    "User-Agent": "BeirutTimeCourseDemo/0.1 (university course project; attributed Commons watch photographs)"
                },
            ),
            timeout=15,
        ) as response:
            content = response.read(8_000_001)
            resolved = response.url
        if len(content) > 8_000_000:
            raise ValueError(f"{asset['id']}: byte limit")
        Image.MAX_IMAGE_PIXELS = 20_000_000
        with Image.open(io.BytesIO(content)) as probe:
            if (
                probe.width * probe.height > 20_000_000
                or probe.format not in ("JPEG", "PNG")
                or getattr(probe, "n_frames", 1) != 1
            ):
                raise ValueError(f"{asset['id']}: image class or pixel limit")
            probe.verify()
        with Image.open(io.BytesIO(content)) as source:
            source.load()
            oriented = ImageOps.exif_transpose(source).convert("RGB")
            clean = Image.new("RGB", oriented.size)
            clean.paste(oriented)
            clean.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        target = ROOT / asset["planned_local_path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        clean.save(
            target,
            format="PNG" if target.suffix == ".png" else "JPEG",
            **({} if target.suffix == ".png" else {"quality": 88, "optimize": True}),
        )
        local = attributed(target.read_bytes(), asset)
        target.write_bytes(local)
        asset.update(
            resolved_url=resolved,
            source_sha256=hashlib.sha256(content).hexdigest(),
            source_bytes=len(content),
            local_sha256=hashlib.sha256(local).hexdigest(),
            local_bytes=len(local),
            local_dimensions=list(clean.size),
            local_url="/demo/watches/" + target.name,
            changes="Oriented, metadata removed, aspect-preserving resize to at most 1600 pixels; JPEG/PNG re-encoded.",
            derivative_license=asset["license"],
            derivative_license_url=asset["license_url"],
        )
        MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        print(asset["id"], asset["local_sha256"], len(local), flush=True)
        time.sleep(10)


if __name__ == "__main__":
    main()
