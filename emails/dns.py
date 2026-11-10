"""Checks a domain's email records in DNS, for the Management page.

The records themselves are added where the domain's DNS is managed (GoDaddy for
tahoeneighborhoodtable.com). These checks only read them.
"""

import dns.exception
import dns.resolver
from django.core.cache import cache
from django.utils.translation import gettext as _

CACHE_SECONDS = 600

# The record each email service signs its emails with (DKIM), so receivers can trust them.
SIGNATURE_RECORDS = {
    "resend": ("resend._domainkey", "TXT"),
    "brevo": ("brevo1._domainkey", "CNAME"),
    "google": ("google._domainkey", "TXT"),
}


class LookupFailed(Exception):
    pass


def _resolver():
    resolver = dns.resolver.Resolver()
    resolver.timeout = 2
    resolver.lifetime = 3
    return resolver


def lookup(name, record_type):
    """The records' text, [] when there are none, or LookupFailed when DNS couldn't be asked."""
    try:
        answer = _resolver().resolve(name, record_type)
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return []
    except (dns.exception.DNSException, OSError) as exc:
        raise LookupFailed(str(exc)) from exc
    if record_type == "TXT":
        return [b"".join(r.strings).decode("utf-8", "replace") for r in answer]
    if record_type == "MX":
        return [str(r.exchange).rstrip(".") for r in sorted(answer, key=lambda r: r.preference)]
    return [r.to_text().rstrip(".") for r in answer]


def _records(domain, service):
    """The DNS answers the checks need, kept for ten minutes. None stands for a lookup that failed."""
    key = f"emails:dns:{domain}:{service}"
    found = cache.get(key)
    if found is None:
        names = {"mx": (domain, "MX"), "dmarc": (f"_dmarc.{domain}", "TXT")}
        if service in SIGNATURE_RECORDS:
            name, record_type = SIGNATURE_RECORDS[service]
            names["signature"] = (f"{name}.{domain}", record_type)
        found = {}
        for item, (name, record_type) in names.items():
            try:
                found[item] = lookup(name, record_type)
            except LookupFailed:
                found[item] = None
        cache.set(key, found, CACHE_SECONDS)
    return found


def forget(domain, service=""):
    cache.delete(f"emails:dns:{domain}:{service}")


def check(domain, service=""):
    """What DNS says about email for the domain: a list of {"label", "state", "text"}.

    state is "ok", "warn" (something to fix or add) or "unknown" (DNS couldn't be checked).
    """
    found = _records(domain, service)
    unknown = _("Couldn’t check DNS just now. Try again later.")
    rows = []

    label = _("Mail to @%(domain)s") % {"domain": domain}
    hosts = found["mx"]
    if hosts is None:
        rows.append({"label": label, "state": "unknown", "text": unknown})
    elif hosts:
        rows.append({"label": label, "state": "ok", "text": _(
            "Received by %(host)s, so replies to the site’s emails reach you.") % {"host": hosts[0]}})
    else:
        rows.append({"label": label, "state": "warn", "text": _(
            "No mail server receives email for %(domain)s, so replies to the site’s emails bounce. Set up email "
            "for the domain, or send replies to another address.") % {"domain": domain}})

    records = found["dmarc"]
    if records is None:
        rows.append({"label": "DMARC", "state": "unknown", "text": unknown})
    else:
        records = [r for r in records if r.lower().startswith("v=dmarc1")]
        if records:
            rows.append({"label": "DMARC", "state": "ok", "text": _("In place: %(record)s") % {"record": records[0]}})
        else:
            rows.append({"label": "DMARC", "state": "warn", "text": _(
                "Recommended, so Gmail and others trust the site’s emails. At GoDaddy, add a TXT record named "
                "_dmarc with the value v=DMARC1; p=none;")})

    if "signature" in found:
        label = _("Email signature (DKIM)")
        records = found["signature"]
        if records is None:
            rows.append({"label": label, "state": "unknown", "text": unknown})
        elif records:
            rows.append({"label": label, "state": "ok", "text": _("In place.")})
        else:
            rows.append({"label": label, "state": "warn", "text": _(
                "Missing. Add the DNS records the email service shows for your domain, then check again.")})
    return rows
