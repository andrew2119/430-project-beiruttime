"""Encrypted recovery payloads retain the language selected at request time."""
import json


def recovery_payload(token, locale):
    if locale not in {'en', 'ar'}:
        raise ValueError('Unsupported language')
    return json.dumps({'token': token, 'locale': locale}, separators=(',', ':'))


def recovery_details(payload):
    # Existing encrypted captures contain only the URL-safe token.
    if not payload.startswith('{'):
        return payload, 'en'
    details = json.loads(payload)
    if set(details) != {'token', 'locale'} or details['locale'] not in {'en', 'ar'} or not isinstance(details['token'], str):
        raise ValueError('Invalid recovery message')
    return details['token'], details['locale']
