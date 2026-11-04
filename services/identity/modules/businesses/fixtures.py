"""Opt-in sample organizations created through real operator commands."""

import os
from uuid import UUID
from bt_bulkheads import DependencyClient, Unavailable


async def seed(settings):
    token = os.environ.get("BT_SAMPLE_OPERATOR_TOKEN")
    colleague = os.environ.get("BT_SAMPLE_COLLEAGUE_ID")
    if not token or not colleague:
        raise ValueError(
            "A current authorized operator token and existing sample colleague are required"
        )
    UUID(colleague)
    client = DependencyClient(
        "identity-sample-commands",
        os.getenv("L02_IDENTITY_URL", "http://127.0.0.1:8000"),
        timeout=2,
        concurrency=1,
    )
    try:
        for kind, name, capabilities in [
            ("dealer", "Sample Beirut Watch House", ["sales", "servicing"]),
            ("brand", "Sample Cedar Atelier", ["sales", "customization", "servicing"]),
        ]:
            response = await client.request(
                "POST",
                "/v1/businesses",
                headers={
                    "Authorization": "Bearer " + token,
                    "Idempotency-Key": "sample-official-" + kind + "-v1",
                },
                json={
                    "legal_name": name + " SAL",
                    "public_name": name,
                    "kind": kind,
                    "capabilities": capabilities,
                    "assurance_reference": "SAMPLE-COMMUNICATION-" + kind.upper(),
                    "reason": "Labeled sample official business approved through platform communication",
                    "sample": True,
                },
            )
            if isinstance(response, Unavailable) or response.status_code != 200:
                raise RuntimeError(
                    "Sample onboarding was not accepted; no success is simulated"
                )
            business = response.json()
            response = await client.request(
                "POST",
                "/v1/memberships",
                headers={
                    "Authorization": "Bearer " + token,
                    "Idempotency-Key": "sample-colleague-" + kind + "-v1",
                },
                json={
                    "business_id": business["id"],
                    "subject_id": colleague,
                    "capabilities": [
                        "business.stock.write",
                        "business.jobs.write",
                        "business.records.read",
                    ],
                    "qualifications": ["Sample business intake training"],
                    "intervention_scope": "Own sample business stock and intake only",
                    "reason": "Sample colleague explicitly authorized by the operator",
                },
            )
            if isinstance(response, Unavailable) or response.status_code != 200:
                raise RuntimeError(
                    "Sample staff grant was not accepted; retry with the same fixture keys"
                )
    finally:
        await client.aclose()
