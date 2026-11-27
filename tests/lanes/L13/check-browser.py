"""Real local Identity/Catalog/Pricing/Orders browser journey on isolated proof databases.
Run only through bt-heavy.sh. Owns and stops every child/browser it starts.
"""

import io
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import jwt
import httpx
from PIL import Image
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from portable_paths import tool_bin

ROOT = Path(__file__).resolve().parents[3]
TOOLS = tool_bin(ROOT)
STATE = ROOT / ".venv/l13-live-proof"
STATE.mkdir(parents=True, exist_ok=True)
ORIGIN = "http://127.0.0.1:58130"
PORTS = {"identity": 58131, "catalog": 58132, "pricing": 58134, "orders": 58135}
INCLUDE_AUCTION = os.environ.get("L13_PROOF_AUCTION") == "1"
if INCLUDE_AUCTION:
    PORTS["auction"] = 58133
PY = ROOT / ".venv/bin/python"
base_paths = [
    ROOT / "packages" / name / "src"
    for name in ("runtime", "contracts-core", "events", "bulkheads")
] + [ROOT / ".venv/l13-contracts"]
config = json.loads(
    subprocess.check_output(
        [str(ROOT / "infra/foundation/compose.sh"), "config", "--format", "json"]
    )
)
pg = config["services"]["postgres"]
port = next(p["published"] for p in pg["ports"] if p["target"] == 5432)
admin = f"postgresql://postgres:{pg['environment']['POSTGRES_PASSWORD']}@127.0.0.1:{port}/postgres"
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
private = key.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()
public = (
    key.public_key()
    .public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    .decode()
)
env = {
    **os.environ,
    "PATH": str(TOOLS) + os.pathsep + os.environ["PATH"],
    "TEST_DATABASE_ADMIN_URL": admin,
    "BT_AUTH_PRIVATE_KEY": private,
    "BT_AUTH_PUBLIC_KEY": public,
    "BT_SERVICE_AUTH_PRIVATE_KEY": private,
    "BT_SERVICE_AUTH_PUBLIC_KEY": public,
    "BT_AUTH_ISSUER": "beirut-time-identity",
    "BT_AUTH_AUDIENCE": "beirut-time",
    "BT_LOCAL_HTTP": "1",
    "BT_ENVIRONMENT": "demo",
    "BT_ALLOWED_WEB_ORIGINS": ORIGIN,
    "BT_PUBLIC_WEB_ORIGINS": ORIGIN,
    "BT_WEB_ORIGIN": ORIGIN,
    "BT_SIMULATED_PAYMENT_SECRET": "synthetic-local-proof-secret-never-real-money",
    "L13_STATE_DIR": str(STATE),
    "CHROME_DEVTOOLS_AXI_SESSION": "bt-s2-l13-proof",
    "CHROME_DEVTOOLS_AXI_BROWSER_URL": "http://127.0.0.1:58139",
}
for name, p in PORTS.items():
    url = f"http://127.0.0.1:{p}"
    for prefix in ("BT_", ""):
        for suffix in ("_URL", "_API_URL"):
            env[prefix + name.upper() + suffix] = url
children = []
handles = []
service_env = {}


def ready(url):
    for _ in range(150):
        try:
            if httpx.get(url, timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise RuntimeError("Proof did not become ready: " + url)


def call(name, method, path, body=None, token=None, **kwargs):
    headers = {
        "Origin": ORIGIN,
        **({"Authorization": "Bearer " + token} if token else {}),
        **kwargs.pop("headers", {}),
    }
    r = httpx.request(
        method,
        f"http://127.0.0.1:{PORTS[name]}" + path,
        json=body,
        headers=headers,
        timeout=8,
        **kwargs,
    )
    if r.status_code not in (200, 201):
        raise RuntimeError(
            f"{name} {method} {path}: {r.status_code} {r.json().get('error', {}).get('code')}"
        )
    return r.json()


def chrome(*args, script=None):
    result = subprocess.run(
        ["chrome-devtools-axi", *args],
        input=script,
        text=True,
        capture_output=True,
        env=env,
        timeout=240,
    )
    if result.returncode:
        raise RuntimeError(result.stderr + "\n" + result.stdout)
    return result.stdout


def js(file, fixture):
    return chrome(
        "run",
        script="const fixture="
        + json.dumps(fixture)
        + ";\n"
        + (ROOT / "tests/lanes/L13" / file).read_text(),
    )


def screenshots(path, name, *, selector=".payment-fees,.withdrawal-row"):
    shots = STATE / "shots"
    shots.mkdir(exist_ok=True)
    for width in (1280, 390):
        for language in ("en", "ar"):
            for theme in ("light", "dark"):
                chrome(
                    "emulate",
                    "--viewport",
                    f"{width}x2000x1" + (",mobile,touch" if width == 390 else ""),
                )
                chrome("open", ORIGIN + "/" + language + path)
                js("browser-theme.js", {"theme": theme, "selector": selector})
                output = shots / f"{name}-{language}-{theme}-{width}.png"
                subprocess.run(
                    [
                        "node",
                        str(ROOT / "tests/lanes/L13/capture-headless.mjs"),
                        ORIGIN,
                        str(output),
                    ],
                    check=True,
                    timeout=60,
                )
                with Image.open(output) as image:
                    if image.width != width:
                        raise RuntimeError("Screenshot width mismatch")


try:
    for p in [58130, 58139, *PORTS.values()]:
        subprocess.run(
            ["lsof", "-nP", f"-iTCP:{p}", "-sTCP:LISTEN"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", p))
    for name, p in PORTS.items():
        local = {
            **env,
            "BT_SERVICE_NAME": name,
            "L13_PORT": str(p),
            "BT_MODULES_PATH": str(ROOT / f"services/{name}/modules"),
            "PYTHONPATH": os.pathsep.join(
                map(
                    str,
                    [
                        *base_paths,
                        ROOT / f"services/{name}/runtime",
                        ROOT / f"services/{name}",
                    ],
                )
            ),
        }
        service_env[name] = local
        log = (STATE / (name + ".log")).open("w")
        handles.append(log)
        child = subprocess.Popen(
            [str(PY), str(ROOT / "tests/lanes/L13/proof-service.py")],
            env=local,
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        children.append(child)
        ready(f"http://127.0.0.1:{p}/health/ready")
    suffix = str(int(time.time()))
    password = "Synthetic-only-Password-138!"
    users = {}
    for role in ("operator", "seller", "buyer"):
        email = f"l13-{role}-{suffix}@example.test"
        result = call(
            "identity",
            "POST",
            "/v1/accounts/register",
            {"email": email, "password": password, "display_name": "DEMO " + role},
            headers={"Idempotency-Key": "register-" + role + "-" + suffix},
        )
        users[role] = {
            "email": email,
            "token": result["access_token"],
            "id": result["account"]["id"],
        }
    db = json.loads((STATE / "identity.json").read_text())
    subprocess.run(
        [
            str(PY),
            "-m",
            "service_app.bootstrap_operator",
            "--email",
            users["operator"]["email"],
            "--reason",
            "Synthetic isolated marketplace proof reviewer",
        ],
        env={**service_env["identity"], "BT_DATABASE_URL": db["runtime_url"]},
        check=True,
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
    )
    operator = call(
        "identity",
        "POST",
        "/v1/accounts/login",
        {"email": users["operator"]["email"], "password": password},
    )["access_token"]
    application = call(
        "identity",
        "POST",
        "/v1/private-seller/applications",
        {
            "identity_name": "DEMO synthetic seller",
            "contact": users["seller"]["email"],
            "payout_reference": "DEMO-L13-RECIPIENT",
            "identity_evidence": "DEMO: synthetic identity only",
            "possession_evidence": "DEMO: synthetic possession only",
            "expected_revision": 0,
        },
        users["seller"]["token"],
        headers={"Idempotency-Key": "private-submit-" + suffix},
    )
    case = application.get("application", application)
    assigned = call(
        "identity",
        "POST",
        "/v1/private-reviews",
        {
            "application_id": case["id"],
            "reviewer_id": users["operator"]["id"],
            "reason": "Synthetic independent identity review",
        },
        operator,
        headers={"Idempotency-Key": "assign-case-" + suffix},
    )
    call(
        "identity",
        "POST",
        "/v1/private-reviews/" + assigned["id"] + "/verdict",
        {
            "revision": assigned["revision"],
            "application_revision": assigned["application_revision"],
            "state": "approved",
            "reason": "Synthetic isolated identity proof checked",
        },
        operator,
        headers={"Idempotency-Key": "review-case-" + suffix},
    )
    seller = call(
        "identity",
        "POST",
        "/v1/accounts/login",
        {"email": users["seller"]["email"], "password": password},
    )["access_token"]
    listings = []
    for index in range(3 if INCLUDE_AUCTION else 2):
        facts = {
            "brand": "Sample",
            "model": "Illustrative L13 watch " + str(index),
            "reference": "DEMO-L13-" + str(index),
            "year": 2020,
            "condition": "Synthetic sample condition, not an actual watch",
            "component_wear": {"case": "Sample condition only"},
            "location": "Beirut",
            "included": [],
            "no_documents": True,
            "modified": False,
            "modifications": [],
            "ownership_confirmed": True,
            "sale_mode": "auction" if index == 2 else "fixed_price",
            "currency": "USD",
            "price_minor": 500000,
        }
        row = call(
            "catalog",
            "POST",
            "/v1/seller/listings",
            {"facts": facts, "demo_key": "DEMO-WATCH-0" + str(index + 1)},
            seller,
            headers={"Idempotency-Key": "sample-create-" + str(index) + "-" + suffix},
        )
        image = io.BytesIO()
        Image.new("RGB", (400, 400), (80, 90, 100)).save(image, format="JPEG")
        response = httpx.post(
            f"http://127.0.0.1:{PORTS['catalog']}/v1/seller/listings/{row['id']}/media",
            content=image.getvalue(),
            headers={
                "Authorization": "Bearer " + seller,
                "Idempotency-Key": "sample-photo-" + str(index) + "-" + suffix,
                "If-Match": str(row["revision"]),
                "Content-Type": "application/octet-stream",
                "X-Media-Kind": "public_photo",
                "X-Public-Safe": "true",
            },
            timeout=8,
        )
        if response.status_code != 201:
            raise RuntimeError("Sample photo failed " + str(response.status_code))
        row = response.json()["listing"]
        quote = call(
            "pricing",
            "POST",
            "/v1/quotes",
            {
                "subject_id": row["id"],
                "subject_revision": row["revision"],
                "purpose": "business_quote",
                "source": "sample",
                "schedule_id": "sample-v1",
                "price_minor": 500000,
                "currency": "USD",
            },
            seller,
            headers={
                "Idempotency-Key": "publication-quote-" + str(index) + "-" + suffix
            },
        )
        row = call(
            "catalog",
            "POST",
            "/v1/seller/listings/" + row["id"] + "/publish",
            {"fee_quote_id": quote["id"], "rules_version": "sample-v1"},
            seller,
            headers={
                "Idempotency-Key": "publish-" + str(index) + "-" + suffix,
                "If-Match": str(row["revision"]),
            },
        )
        listings.append(row["id"])
    auction_result = None
    if INCLUDE_AUCTION:
        from auction_proof import run as prove_auction

        auction_result = prove_auction(
            call,
            seller,
            users["buyer"]["token"],
            users["buyer"]["id"],
            listings[2],
            suffix,
            jwt.encode(
                {
                    "sub": "auction",
                    "type": "service",
                    "iss": "beirut-time-identity",
                    "aud": "pricing",
                    "iat": int(time.time()),
                    "exp": int(time.time()) + 120,
                },
                private,
                algorithm="RS256",
            ),
            expect_pending=os.environ.get("L13_EXPECT_CLOSE_PENDING") == "1",
        )
        (STATE / "auction-result.json").write_text(json.dumps(auction_result, indent=2))
        if os.environ.get("L13_ONLY_AUCTION_BACKEND") == "1":
            print(
                "PASS real accepted bid, canonical close, Pricing winner construction and "
                + auction_result["allocation"]
                + " Orders allocation",
                flush=True,
            )
            raise SystemExit(0)
    subprocess.run(
        ["node", str(ROOT / "web/scripts/generate-nav.mjs")],
        check=True,
        env=env,
        cwd=ROOT,
    )
    log = (STATE / "web.log").open("w")
    handles.append(log)
    web = subprocess.Popen(
        [
            "node",
            str(ROOT / "web/node_modules/next/dist/bin/next"),
            "dev",
            "--hostname",
            "127.0.0.1",
            "--port",
            "58130",
        ],
        env=env,
        cwd=ROOT / "web",
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    children.append(web)
    ready(ORIGIN + "/en/checkout")
    fixture = {
        "origin": ORIGIN,
        "buyerEmail": users["buyer"]["email"],
        "sellerEmail": users["seller"]["email"],
        "password": password,
        "purchaseListing": listings[0],
        "withdrawListing": listings[1],
        "auction": auction_result,
        "winnerCheckoutOnly": os.environ.get("L13_WINNER_CHECKOUT_ONLY") == "1",
    }
    browser_log = (STATE / "headless.log").open("w")
    handles.append(browser_log)
    browser = subprocess.Popen(
        [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--remote-debugging-address=127.0.0.1",
            "--remote-debugging-port=58139",
            "--user-data-dir=" + str(STATE / "headless"),
            "about:blank",
        ],
        stdout=browser_log,
        stderr=subprocess.STDOUT,
    )
    children.append(browser)
    ready("http://127.0.0.1:58139/json/version")
    chrome("open", ORIGIN + "/en/account")
    chrome("emulate", "--viewport", "1280x900x1")
    flow = js("browser-flow.js", fixture)
    (STATE / "flow.json").write_text(flow)
    # The runner prints one bounded JSON result; refs are synthetic, never credentials.
    import re

    match = re.search(r'\{"realIdentity":true.*\}', flow)
    if not match:
        raise RuntimeError("Browser result missing")
    fixture["orderId"] = json.loads(match.group())["orderId"]
    if auction_result:
        (STATE / "auction-browser.json").write_text(js("browser-auction.js", fixture))
        if auction_result["allocation"] == "succeeded":
            winner_checkout = call(
                "orders",
                "GET",
                "/v1/orders/" + auction_result["orderId"] + "/checkout",
                token=users["buyer"]["token"],
            )
            winner_journal = call(
                "orders",
                "GET",
                "/v1/orders/" + auction_result["orderId"] + "/journal",
                token=users["buyer"]["token"],
            )
            if (
                winner_checkout["order"]["state"] != "paid_held"
                or winner_journal["group"]["total_minor"] != 515000
                or {
                    entry["account"]: entry["amount_minor"]
                    for entry in winner_journal["entries"]
                }
                != {"simulated_clearing": 515000, "buyer_held": -515000}
                or winner_journal["payout_authorized"] is not False
            ):
                raise RuntimeError(
                    "Winner browser payment did not post the exact single held-payment group"
                )
        auction_cases = []
        for width in (1280, 390):
            chrome(
                "emulate",
                "--viewport",
                f"{width}x844x3" + (",mobile,touch" if width == 390 else ""),
            )
            auction_cases.append(
                js(
                    "browser-matrix.js"
                    if fixture["winnerCheckoutOnly"]
                    else "browser-auction-matrix.js",
                    {
                        **fixture,
                        "orderId": auction_result.get("orderId"),
                        "width": width,
                    },
                )
            )
        (STATE / "auction-matrix.json").write_text(json.dumps(auction_cases, indent=2))
        screenshots(
            "/checkout/" + auction_result["orderId"]
            if fixture["winnerCheckoutOnly"]
            else "/watches/" + auction_result["listingId"],
            "auction-checkout" if fixture["winnerCheckoutOnly"] else "auction",
            selector=".payment-fees"
            if fixture["winnerCheckoutOnly"]
            else ".checkout-slot",
        )
        if os.environ.get("L13_ONLY_AUCTION") == "1":
            print(
                "PASS connected winner checkout from owned reservations in 8 locale/theme/viewport cases; watch result slot not included"
                if fixture["winnerCheckoutOnly"]
                else "PASS connected actual Auction decision, exact Pricing construction and fail-closed winner slot"
                if auction_result["allocation"] == "pending"
                else "PASS connected actual winner allocation and explicitly reviewed simulated checkout",
                flush=True,
            )
            raise SystemExit(0)
    evidence = []
    for width in (1280, 390):
        chrome(
            "emulate",
            "--viewport",
            f"{width}x{844 if width == 390 else 900}x{3 if width == 390 else 1}"
            + (",mobile,touch" if width == 390 else ""),
        )
        matrix = js("browser-matrix.js", {**fixture, "width": width})
        evidence.append(matrix)
    (STATE / "matrix.json").write_text(json.dumps(evidence, indent=2))
    screenshots("/checkout/" + fixture["orderId"], "checkout")
    chrome("open", ORIGIN + "/en/account")
    withdrawal = js("browser-withdrawal.js", fixture)
    (STATE / "withdrawal.json").write_text(withdrawal)
    withdrawal_cases = []
    for width in (1280, 390):
        chrome(
            "emulate",
            "--viewport",
            f"{width}x{844 if width == 390 else 900}x{3 if width == 390 else 1}"
            + (",mobile,touch" if width == 390 else ""),
        )
        withdrawal_cases.append(
            js("browser-withdrawal-matrix.js", {**fixture, "width": width})
        )
    (STATE / "withdrawal-matrix.json").write_text(
        json.dumps(withdrawal_cases, indent=2)
    )
    screenshots("/seller/withdrawals", "withdrawals")
    withdrawn = call(
        "catalog",
        "GET",
        "/v1/listings/" + listings[1] + "/withdrawals/current",
        token=seller,
    )
    paid_withdraw = call(
        "catalog",
        "GET",
        "/v1/listings/" + listings[0] + "/withdrawals/current",
        token=seller,
    )
    if withdrawn["status"] != "succeeded" or paid_withdraw["status"] != "denied":
        raise RuntimeError("Canonical withdrawal proof failed")
    # Canonical DB verifies the actual browser confirmation, not text-only success.
    paid = call(
        "orders",
        "GET",
        "/v1/orders/" + fixture["orderId"] + "/checkout",
        token=users["buyer"]["token"],
    )
    journal = call(
        "orders",
        "GET",
        "/v1/orders/" + fixture["orderId"] + "/journal",
        token=users["buyer"]["token"],
    )
    if (
        paid["order"]["state"] != "paid_held"
        or paid["order"]["total_minor"] != 515000
        or len(journal["entries"]) != 2
        or sum(e["amount_minor"] for e in journal["entries"]) != 0
    ):
        raise RuntimeError("Canonical payment proof failed")
    (STATE / "public-result.json").write_text(
        json.dumps(
            {
                "origin": ORIGIN,
                "order_id": fixture["orderId"],
                "listing_ids": listings,
                "simulated": True,
                "balanced_groups": 1,
                "browser_cases": 16,
                "screenshots": 16,
                "paid_withdrawal_denied": True,
            },
            indent=2,
        )
    )
    print(
        "PASS real browser exact USD 5150 simulated checkout, balanced journal, guarded withdrawal and 16 locale/theme/viewport cases"
    )
finally:
    try:
        chrome("stop")
    except Exception:
        pass
    for child in reversed(children):
        if child.poll() is None:
            child.terminate()
    for child in reversed(children):
        try:
            child.wait(timeout=15)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
    for handle in handles:
        handle.close()
