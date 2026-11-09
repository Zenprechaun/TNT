import stripe
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.urls import reverse
from django.utils import translation

from donations import stripe_api
from donations.models import StripeSetup, stripe_mode
from donations.services import donation_name, tax_note


class Command(BaseCommand):
    help = (
        "Connects the site to the Stripe account in STRIPE_SECRET_KEY: sets up the webhook that tells the site "
        "about payments, the Donation product, and the page where monthly donors change or stop their donation. "
        "Run it after adding the key, and again after switching from a test key to a live one. "
        "Running it again is safe."
    )

    def add_arguments(self, parser):
        parser.add_argument("--url", default=settings.SITE_URL, help="The site's address (default: SITE_URL).")

    def handle(self, *args, url, **options):
        mode = stripe_mode()
        if not mode:
            raise CommandError("Add STRIPE_SECRET_KEY to /srv/tahoetable/.env, restart the site, then run this again.")
        url = url.rstrip("/")
        if not url.startswith("https://"):
            raise CommandError("Stripe only sends payment updates to https:// addresses.")
        livemode = mode == "live"
        setup, _ = StripeSetup.objects.get_or_create(livemode=livemode, defaults={"site_url": url})
        setup.site_url = url
        try:
            self.webhook(setup, url + reverse("donations:webhook"))
            self.products(setup)
            self.portal(setup, url)
        except stripe_api.StripeError as exc:
            setup.save()
            raise CommandError(f"Stripe said: {exc}") from exc
        setup.save()
        kind = "real payments" if livemode else "test payments (no real money moves)"
        self.stdout.write(self.style.SUCCESS(f"Stripe is connected for {kind}."))
        if setup.portal_login_url:
            self.stdout.write(f"Monthly donors can manage their donation at {setup.portal_login_url}")

    def webhook(self, setup, endpoint_url):
        endpoints = [e for e in stripe_api.list_webhook_endpoints() if e.get("url") == endpoint_url]
        ours = next((e for e in endpoints if e.get("id") == setup.webhook_endpoint), None)
        if ours and setup.webhook_secret:
            stripe_api.update_webhook_endpoint(ours["id"], enabled_events=stripe_api.WEBHOOK_EVENTS, disabled=False)
            self.stdout.write("The webhook was already set up. Its list of events is up to date.")
        else:
            endpoint = stripe_api.create_webhook_endpoint(
                url=endpoint_url,
                enabled_events=stripe_api.WEBHOOK_EVENTS,
                api_version=stripe.api_version,
                description="Tahoe Neighborhood Table website: donations",
            )
            setup.webhook_endpoint = endpoint["id"]
            setup.webhook_secret = endpoint["secret"]
            self.stdout.write(f"Set up the webhook: Stripe will report payments to {endpoint_url}")
        others = [e["id"] for e in endpoints if e.get("id") != setup.webhook_endpoint]
        if others:
            self.stdout.write(self.style.WARNING(
                "Other webhooks in Stripe also send to this address: " + ", ".join(others)
                + ". If you don't need them, delete them in the Stripe Dashboard under Developers > Webhooks."))

    def products(self, setup):
        products = dict(setup.products or {})
        for code, _name in settings.LANGUAGES:
            with translation.override(code):
                params = {"name": donation_name()}
                if tax_note():
                    params["description"] = tax_note()
            if products.get(code):
                stripe_api.update_product(products[code], **params)
            else:
                product = stripe_api.create_product(**params, metadata={"site": "tahoeneighborhoodtable", "language": code})
                products[code] = product["id"]
        setup.products = products
        self.stdout.write("The Donation product is ready in English and Spanish.")

    def portal(self, setup, url):
        if setup.portal_configuration:
            self.stdout.write("The page for managing monthly donations was already set up.")
            return
        config = stripe_api.create_portal_configuration(
            business_profile={"headline": "Tahoe Neighborhood Table: manage your monthly donation"},
            default_return_url=url + "/",
            features={
                "subscription_cancel": {"enabled": True, "mode": "at_period_end"},
                "payment_method_update": {"enabled": True},
                "invoice_history": {"enabled": True},
                "customer_update": {"enabled": True, "allowed_updates": ["email", "name"]},
            },
            login_page={"enabled": True},
        )
        setup.portal_configuration = config["id"]
        setup.portal_login_url = (config.get("login_page") or {}).get("url") or ""
        self.stdout.write("Set up the page where monthly donors change or stop their donation.")
