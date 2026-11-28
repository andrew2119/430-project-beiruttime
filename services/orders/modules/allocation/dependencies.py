"""Backward-compatible imports; runtime owns the one dependency adapter."""
from service_app.orders_dependencies import (
    clients, principal, service, organization_principal, quote, delivery_headers,
)

__all__ = ['clients', 'principal', 'service', 'organization_principal', 'quote', 'delivery_headers']
