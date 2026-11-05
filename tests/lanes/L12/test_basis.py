from datetime import datetime, timedelta, timezone
from uuid import uuid4
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from conftest import BUYER, OTHER, headers


def token(app,subject='pricing',kind='service',audience='auction'):
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    private=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
    app.state.settings.service_auth_public_key=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    now=datetime.now(timezone.utc)
    return {'Authorization':'Bearer '+jwt.encode({'sub':subject,'type':kind,'aud':audience,'iss':app.state.settings.auth_issuer,'iat':now,'exp':now+timedelta(minutes=1)},private,algorithm='RS256')}


async def test_current_quote_basis_binds_admission_before_freeze(api):
    client,app,fixture,id=api
    quote=fixture.quote(id,2)
    fixture.lose_response=True
    result=await client.post(f'/v1/auctions/{id}/prebid-buy-now',headers=headers(),json={'expected_revision':2,'quote_id':quote})
    assert result.json()['status']=='pending'
    url=f'/internal/v1/auctions/{id}/prebid-basis?quote_id={quote}&buyer_id={BUYER}'
    assert (await client.get(url,headers=headers())).status_code==503  # Service verifier is not configured.
    auth=token(app)
    current=await client.get(url,headers=auth)
    assert current.status_code==200,current.text
    value=current.json()
    assert value['admission_revision']==2 and value['current_revision']==3
    assert value['buyer_id']==str(BUYER) and value['quote_id']==quote
    assert value['total_minor']==515000 and value['currency']=='USD'
    assert value['mode']=='prebid_pending'
    assert (await client.get(url.replace(str(BUYER),str(OTHER)),headers=auth)).status_code==404
    assert (await client.get(url.replace(quote,str(uuid4())),headers=auth)).status_code==404
    assert (await client.get(url,headers=headers())).status_code==401
    assert (await client.get(url,headers=token(app,subject='catalog'))).status_code==403
    assert (await client.get(url,headers=token(app,kind='access'))).status_code==403
    assert (await client.get(url,headers=token(app,audience='orders'))).status_code==401


async def test_basis_preserves_admission_after_reservation_and_holds_legacy_unknown(api):
    client,app,fixture,id=api
    quote=fixture.quote(id,2)
    result=await client.post(f'/v1/auctions/{id}/prebid-buy-now',headers=headers(),json={'expected_revision':2,'quote_id':quote})
    assert result.json()['status']=='succeeded'
    url=f'/internal/v1/auctions/{id}/prebid-basis?quote_id={quote}&buyer_id={BUYER}'
    auth=token(app,subject='orders')
    response=await client.get(url,headers=auth)
    assert response.status_code==200,response.text
    assert response.json()['admission_revision']==2 and response.json()['current_revision']==4
    async with app.state.pool.acquire() as tx:
        await tx.execute('UPDATE auction_prebid_operations SET admission_revision=NULL')
    assert (await client.get(url,headers=auth)).status_code==409
