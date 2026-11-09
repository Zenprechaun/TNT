"""Every call the site makes to Stripe, in one place. Each one returns plain dictionaries.

The tests replace these functions, so nothing in the test suite talks to Stripe.
"""

import json

import stripe
from django.conf import settings

# Events the site's webhook listens for. `connect_stripe` subscribes to exactly these.
WEBHOOK_EVENTS = [
    "checkout.session.completed",
    "checkout.session.async_payment_succeeded",
    "checkout.session.async_payment_failed",
    "checkout.session.expired",
    "invoice.paid",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "charge.refunded",
]


class StripeError(Exception):
    """Stripe couldn't be reached, or turned the request down."""


def _plain(obj):
    return obj.to_dict() if hasattr(obj, "to_dict") else dict(obj)


def _call(function, *args, **params):
    try:
        return _plain(function(*args, api_key=settings.STRIPE_SECRET_KEY, **params))
    except stripe.StripeError as exc:
        raise StripeError(str(exc)) from exc


def create_checkout_session(**params):
    return _call(stripe.checkout.Session.create, **params)


def retrieve_checkout_session(session_id):
    return _call(stripe.checkout.Session.retrieve, session_id)


def create_portal_session(customer, return_url, configuration=""):
    params = {"customer": customer, "return_url": return_url}
    if configuration:
        params["configuration"] = configuration
    return _call(stripe.billing_portal.Session.create, **params)


def create_customer(**params):
    return _call(stripe.Customer.create, **params)


def create_product(**params):
    return _call(stripe.Product.create, **params)


def update_product(product_id, **params):
    return _call(stripe.Product.modify, product_id, **params)


def create_webhook_endpoint(**params):
    return _call(stripe.WebhookEndpoint.create, **params)


def update_webhook_endpoint(endpoint_id, **params):
    return _call(stripe.WebhookEndpoint.modify, endpoint_id, **params)


def list_webhook_endpoints():
    return _call(stripe.WebhookEndpoint.list, limit=100).get("data", [])


def create_portal_configuration(**params):
    return _call(stripe.billing_portal.Configuration.create, **params)


def verify_event(payload, signature, secrets):
    """The event in a webhook request, if its signature matches one of our webhook secrets. Otherwise None."""
    for secret in secrets:
        if not secret:
            continue
        try:
            stripe.WebhookSignature.verify_header(payload, signature, secret, stripe.Webhook.DEFAULT_TOLERANCE)
        except stripe.SignatureVerificationError:
            continue
        return json.loads(payload)
    return None
