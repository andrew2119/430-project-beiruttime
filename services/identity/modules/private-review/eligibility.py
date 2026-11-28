"""Current internal publication authority with a serialized review boundary."""
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError, model_validator
from bt_contracts.catalog.listings.eligibility import PublicationEligibility
from bt_contracts_core.errors import PublicError
from bt_runtime.app.db import unit_of_work

router = APIRouter()


class Binding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["listing-eligibility.v1"]
    operation_id: str = Field(min_length=1, max_length=128)
    subject_id: UUID
    listing_id: UUID
    watch_id: UUID
    actor_id: UUID
    organization_id: UUID | None
    expected_revision: StrictInt = Field(ge=1)
    identity_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def listing_subject(self):
        if self.subject_id != self.listing_id:
            raise ValueError("Subject must equal listing")
        return self


async def catalog_service(request: Request):
    settings = request.app.state.settings
    if not settings.service_auth_public_key:
        raise HTTPException(503)
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token or len(token) > 8192:
        raise HTTPException(401)
    try:
        claims = jwt.decode(
            token, settings.service_auth_public_key, algorithms=["RS256"],
            issuer=settings.auth_issuer, audience="identity",
            options={"require": ["exp", "iat", "iss", "aud", "sub", "type"]},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(401) from None
    if claims["type"] != "service" or claims["sub"] != "catalog":
        raise HTTPException(403)


async def seller_authority(tx, body):
    account = await tx.fetchrow(
        "SELECT status,access_revision FROM identity_accounts WHERE id=$1 FOR UPDATE", body.actor_id)
    if not account or account["status"] != "active":
        return False, 1
    grants = await tx.fetch(
        """SELECT role,permissions FROM identity_access_grants WHERE subject_id=$1
        AND organization_id IS NOT DISTINCT FROM $2 AND revoked_at IS NULL FOR SHARE""",
        body.actor_id, body.organization_id)
    revision = account["access_revision"]
    if body.organization_id is None:
        approved = await tx.fetchval(
            """SELECT r.id FROM l02_private_reviews r
            JOIN identity_private_applications a ON a.id=r.application_id
            WHERE r.applicant_id=$1 AND a.subject_id=$1 AND r.state='approved'
            AND a.status='approved' AND r.application_revision=a.revision FOR SHARE OF r,a""", body.actor_id)
        return bool(approved and any(g["role"] == "private_seller" and
                    "identity.listings.publish" in g["permissions"] for g in grants)), revision
    business = await tx.fetchrow("SELECT * FROM l02_businesses WHERE id=$1 FOR SHARE", body.organization_id)
    membership = await tx.fetchrow(
        "SELECT * FROM l02_memberships WHERE business_id=$1 AND subject_id=$2 FOR SHARE",
        body.organization_id, body.actor_id)
    allowed = bool(business and business["state"] == "active" and "sales" in business["capabilities"]
                   and membership and membership["state"] == "active" and "business.stock.write" in membership["capabilities"]
                   and any(g["role"] == business["kind"] and "business.stock.write" in g["permissions"] for g in grants))
    return allowed, revision


@router.post("/internal/v1/listing-eligibility/validate", dependencies=[Depends(catalog_service)])
async def validate(body: Binding, request: Request, response: Response,
                   key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128)):
    response.headers["Cache-Control"] = "no-store"
    if key != body.operation_id:
        raise PublicError("idempotency_conflict", "Use the publication operation key.", status=409)
    binding = body.model_dump(mode="json")
    async with unit_of_work(request.app.state.pool, lock_key="listing-eligibility:" + str(body.watch_id)) as tx:
        allowed, revision = await seller_authority(tx, body)
        result = dict(binding, state="denied", revision=revision, current=True,
                      duplicate_review="denied", pending_reason=None, next_actor=None, next_review_at=None)
        if allowed:
            result.update(state="pending", duplicate_review="required", pending_reason="listing_review_required", next_actor="assigned_reviewer",
                          next_review_at=datetime.now(timezone.utc) + timedelta(hours=24))
            provider = getattr(request.app.state, "listing_eligibility_review", None)
            if provider is not None:
                try:
                    async with asyncio.timeout(2):
                        # The provider must hold canonical review and duplicate fences until this transaction ends.
                        decision = await provider.validate(tx, dict(binding))
                    proof = PublicationEligibility.model_validate(decision)
                    projected = proof.model_dump(mode="json")
                    if any(projected[name] != value for name, value in binding.items()):
                        raise ValueError("Review binding differs")
                    if proof.state == "eligible" and (not proof.current or proof.duplicate_review != "clear"):
                        raise ValueError("Review is not current")
                    result = projected
                except (TimeoutError, OSError, ValidationError, ValueError, TypeError):
                    pass
        return PublicationEligibility.model_validate(result).model_dump(mode="json")
