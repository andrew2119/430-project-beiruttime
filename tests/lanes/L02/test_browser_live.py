"""Opt-in live service for real-browser review; no browser API interception."""

import asyncio
import json
import os
from pathlib import Path
import pytest
import uvicorn
from conftest import PASSWORD
from test_identity_modules import business, key


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("BT_L02_BROWSER_DEMO") != "1", reason="Opt-in live browser service"
)
async def test_live_browser_service(api):
    client, state, _, app = api
    records = []
    for kind, name in [
        ("dealer", "Sample Beirut Watch House"),
        ("brand", "Sample Cedar Atelier"),
    ]:
        body = {**business(kind), "public_name": name, "legal_name": name + " SAL"}
        if kind == "brand":
            body["capabilities"].append("customization")
        response = await client.post("/v1/businesses", json=body, headers=key())
        assert response.status_code == 200, response.text
        records.append(response.json())
    directory = Path(__file__).resolve().parent / ".contract-runtime"
    directory.mkdir(exist_ok=True)
    stop = directory / "stop-browser"
    stop.unlink(missing_ok=True)
    server = uvicorn.Server(
        uvicorn.Config(
            app, host="127.0.0.1", port=8202, log_level="warning", access_log=False
        )
    )
    running = asyncio.create_task(server.serve())
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.05)
        assert server.started
        (directory / "browser.json").write_text(
            json.dumps(
                {
                    "sample": True,
                    "identity_url": "http://127.0.0.1:8202",
                    "operator_email": str(state["actor"]) + "@example.test",
                    "sample_password": PASSWORD,
                    "colleague_id": str(state["reviewer"]),
                    "applicant_id": str(state["applicant"]),
                    "businesses": records,
                },
                indent=2,
            )
        )
        # A browser fixture is a bounded service, never an overnight pytest wait.
        for _ in range(
            max(1, min(int(os.getenv("BT_L02_BROWSER_SECONDS", "90")), 300))
        ):
            if stop.exists():
                break
            await asyncio.sleep(1)
    finally:
        server.should_exit = True
        await running
        (directory / "browser.json").unlink(missing_ok=True)
