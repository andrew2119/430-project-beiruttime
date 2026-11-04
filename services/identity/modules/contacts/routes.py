import hashlib
import hmac
import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, Header, Request
from pydantic import Field, field_validator
from bt_contracts_core.models import Contract, EventEnvelope
from bt_contracts_core.errors import PublicError
from bt_events import enqueue
from bt_runtime.app.db import unit_of_work
from bt_runtime.principal import CurrentPrincipal
from service_app.identity import consume_reauthentication, live_actor
from .security import principal, require_communications

router = APIRouter(prefix="/v1/contacts", tags=["private-contacts"])
internal_router = APIRouter(
    prefix="/internal/v1/contacts",
    tags=["verified-delivery"],
    dependencies=[Depends(require_communications)],
)


@internal_router.get("/{subject_id}/delivery")
async def delivery(subject_id: UUID, request: Request):
    async with request.app.state.pool.acquire() as tx:
        row = await tx.fetchrow(
            "SELECT * FROM l02_contacts WHERE subject_id=$1", subject_id
        )
    # Only the private Communications service gets verified recipients; no public
    # gateway or pending challenge recipient can enter this projection.
    return {
        "subject_id": str(subject_id),
        "revision": row["revision"] if row else 0,
        "email": row["email"] if row and row["email_verified_at"] else None,
        "phone": row["phone"] if row and row["phone_verified_at"] else None,
        "email_sample": row["email_sample"] if row else False,
        "phone_sample": row["phone_sample"] if row else False,
    }


def digits(value):
    return "".join(str(int(char)) if char.isdecimal() else char for char in value)


class Challenge(Contract):
    channel: Literal["email", "phone"]
    recipient: str = Field(min_length=5, max_length=254)
    revision: int = Field(ge=0)
    proof: str = Field(min_length=32, max_length=200)

    @field_validator("recipient")
    @classmethod
    def clean(cls, value, info):
        # Digit normalization is for telephone numbers, never a different email
        # mailbox with a similar-looking local part.
        return (
            digits(value.strip())
            if info.data.get("channel") == "phone"
            else value.strip()
        )


class Proof(Contract):
    code: str = Field(min_length=6, max_length=6)

    @field_validator("code")
    @classmethod
    def normalize(cls, value):
        value = digits(value)
        if not re.fullmatch(r"[0-9]{6}", value):
            raise ValueError("Six digits required")
        return value


def digest(challenge_id, code):
    return hashlib.sha256((str(challenge_id) + ":" + code).encode()).hexdigest()


def contact(row):
    if not row:
        return {
            "revision": 0,
            "email": None,
            "phone": None,
            "email_verified": False,
            "phone_verified": False,
            "email_sample": False,
            "phone_sample": False,
        }
    return {
        "revision": row["revision"],
        "email": row["email"],
        "phone": row["phone"],
        "email_verified": row["email_verified_at"] is not None,
        "phone_verified": row["phone_verified_at"] is not None,
        "email_sample": row["email_sample"],
        "phone_sample": row["phone_sample"],
    }


@router.get("")
async def read(request: Request, actor: CurrentPrincipal = Depends(principal)):
    async with request.app.state.pool.acquire() as tx:
        row = await tx.fetchrow(
            "SELECT * FROM l02_contacts WHERE subject_id=$1", actor.actor.subject_id
        )
        pending = await tx.fetchrow(
            """SELECT id,expires_at,simulated_code IS NOT NULL AS sample FROM l02_contact_challenges
            WHERE subject_id=$1 AND consumed_at IS NULL AND expires_at>now() AND attempts<5
            ORDER BY created_at DESC LIMIT 1""",
            actor.actor.subject_id,
        )
    return {
        **contact(row),
        "pending_challenge": {
            "id": str(pending["id"]),
            "state": "pending",
            "expires_at": pending["expires_at"].isoformat(),
            "delivery_mode": "sample_simulator"
            if pending["sample"]
            else "delivery_pending",
        }
        if pending
        else None,
    }


@router.post("/challenges")
async def challenge(
    body: Challenge,
    request: Request,
    actor: CurrentPrincipal = Depends(principal),
    key: str = Header(alias="Idempotency-Key", min_length=8, max_length=100),
):
    recipient = body.recipient.lower() if body.channel == "email" else body.recipient
    if body.channel == "email" and not re.fullmatch(
        r"[^\s@]+@[^\s@]+\.[^\s@]+", recipient
    ):
        raise PublicError("invalid_contact", "Enter a valid email address.", status=422)
    if body.channel == "phone" and not re.fullmatch(r"\+[1-9][0-9]{7,14}", recipient):
        raise PublicError(
            "invalid_contact", "Use an international phone number.", status=422
        )
    subject = actor.actor.subject_id
    # Never retain passwords, proof tokens, recipient or code in an operation fingerprint source.
    fingerprint = hashlib.sha256(
        (body.channel + recipient + str(body.revision)).encode()
    ).hexdigest()
    now = datetime.now(timezone.utc)
    async with unit_of_work(
        request.app.state.pool, lock_key="l02.contacts:" + str(subject)
    ) as tx:
        old = await tx.fetchrow(
            "SELECT * FROM l02_contact_operations WHERE subject_id=$1 AND operation_key=$2",
            subject,
            key,
        )
        if old:
            if old["fingerprint"] != fingerprint:
                raise PublicError(
                    "idempotency_conflict", "Operation key already used.", status=409
                )
            return json.loads(old["result"])
        account, _ = await consume_reauthentication(
            tx,
            request,
            body.proof,
            purpose="contact-change",
            binding=body.channel + ":" + recipient,
        )
        if account["id"] != subject:
            raise PublicError(
                "reauthentication_required", "Confirm your password again.", status=403
            )
        row = await tx.fetchrow(
            "SELECT * FROM l02_contacts WHERE subject_id=$1 FOR UPDATE", subject
        )
        if (row["revision"] if row else 0) != body.revision:
            raise PublicError(
                "stale_revision", "Reload the current contact details.", status=409
            )
        recent = await tx.fetch(
            """SELECT created_at FROM l02_contact_challenges WHERE subject_id=$1
            AND created_at > $2::timestamptz - interval '1 hour' ORDER BY created_at DESC LIMIT 5""",
            subject,
            now,
        )
        if len(recent) >= 5 or (
            recent and (now - recent[0]["created_at"]).total_seconds() < 60
        ):
            raise PublicError(
                "verification_limited",
                "Please wait before requesting another code.",
                status=429,
            )
        identity, code = uuid4(), f"{secrets.randbelow(1000000):06d}"
        simulator = os.getenv("BT_CONTACT_SIMULATOR", "0") == "1"
        await tx.execute(
            """UPDATE l02_contact_challenges SET consumed_at=$2,simulated_code=NULL
            WHERE subject_id=$1 AND consumed_at IS NULL""",
            subject,
            now,
        )
        await tx.execute(
            """INSERT INTO l02_contact_challenges
            (id,subject_id,channel,recipient,code_digest,expires_at,simulated_code,contact_revision)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8)""",
            identity,
            subject,
            body.channel,
            recipient,
            digest(identity, code),
            now + timedelta(minutes=10),
            code if simulator else None,
            body.revision,
        )
        result = {
            "id": str(identity),
            "state": "pending",
            "expires_at": (now + timedelta(minutes=10)).isoformat(),
            "delivery_mode": "sample_simulator" if simulator else "delivery_pending",
        }
        await tx.execute(
            "INSERT INTO l02_contact_operations VALUES($1,$2,$3,$4::jsonb)",
            subject,
            key,
            fingerprint,
            json.dumps(result),
        )
        if not simulator:
            await enqueue(
                tx,
                EventEnvelope(
                    type="identity.contact-challenge.v1",
                    source="identity",
                    subject=str(subject),
                    request_id=request.state.request_id,
                    data={
                        "challenge_id": str(identity),
                        "channel": body.channel,
                        "recipient": recipient,
                        "code": code,
                        "expires_at": result["expires_at"],
                    },
                ),
                ["communications"],
            )
    return result


@router.get("/challenges/{challenge_id}/sample-code")
async def sample_code(
    challenge_id: UUID, request: Request, actor: CurrentPrincipal = Depends(principal)
):
    if os.getenv("BT_CONTACT_SIMULATOR", "0") != "1":
        raise PublicError("not_found", "Resource not found.", status=404)
    async with request.app.state.pool.acquire() as tx:
        row = await tx.fetchrow(
            """SELECT simulated_code FROM l02_contact_challenges WHERE id=$1 AND subject_id=$2
            AND consumed_at IS NULL AND expires_at>now() AND attempts<5""",
            challenge_id,
            actor.actor.subject_id,
        )
    if not row:
        raise PublicError(
            "verification_failed", "Request a new verification code.", status=400
        )
    return {
        "sample": True,
        "label": "Sample contact delivery simulator",
        "code": row["simulated_code"],
    }


@router.post("/challenges/{challenge_id}/verify")
async def verify(
    challenge_id: UUID,
    body: Proof,
    request: Request,
    actor: CurrentPrincipal = Depends(principal),
):
    subject, now = actor.actor.subject_id, datetime.now(timezone.utc)
    failed = False
    async with unit_of_work(
        request.app.state.pool, lock_key="l02.contacts:" + str(subject)
    ) as tx:
        current_account, _ = await live_actor(tx, request, lock=True)
        if current_account["id"] != subject:
            raise PublicError(
                "verification_failed", "The code could not be verified.", status=400
            )
        row = await tx.fetchrow(
            "SELECT * FROM l02_contact_challenges WHERE id=$1 AND subject_id=$2 FOR UPDATE",
            challenge_id,
            subject,
        )
        current = await tx.fetchrow(
            "SELECT * FROM l02_contacts WHERE subject_id=$1", subject
        )
        if (
            not row
            or row["consumed_at"]
            or row["expires_at"] <= now
            or row["attempts"] >= 5
        ):
            failed = True
        elif row["contact_revision"] != (current["revision"] if current else 0):
            failed = True
        elif not hmac.compare_digest(
            row["code_digest"], digest(challenge_id, body.code)
        ):
            await tx.execute(
                "UPDATE l02_contact_challenges SET attempts=attempts+1 WHERE id=$1",
                challenge_id,
            )
            failed = True
        else:
            await tx.execute(
                "UPDATE l02_contact_challenges SET consumed_at=$2,simulated_code=NULL WHERE id=$1",
                challenge_id,
                now,
            )
            # Column names are closed server literals, never recipient-controlled SQL.
            column = "email" if row["channel"] == "email" else "phone"
            await tx.execute(
                """INSERT INTO l02_contacts(subject_id) VALUES($1) ON CONFLICT DO NOTHING""",
                subject,
            )
            result = await tx.fetchrow(
                f"""UPDATE l02_contacts SET {column}=$2,{column}_verified_at=$3,{column}_sample=$4,
                revision=revision+1,updated_at=$3 WHERE subject_id=$1 RETURNING *""",
                subject,
                row["recipient"],
                now,
                row["simulated_code"] is not None,
            )
            await enqueue(
                tx,
                EventEnvelope(
                    type="identity.contact-verified.v1",
                    source="identity",
                    subject=str(subject),
                    request_id=request.state.request_id,
                    data={
                        "subject_id": str(subject),
                        "channel": column,
                        "revision": result["revision"],
                        "sample": result[column + "_sample"],
                    },
                ),
                ["communications", "auction"],
            )
    # Wrong attempts must commit; an exception inside the UoW would undo the limit.
    if failed:
        raise PublicError(
            "verification_failed",
            "The code could not be verified. Request a new code if needed.",
            status=400,
        )
    return contact(result)
