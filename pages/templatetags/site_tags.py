"""Template helpers for the home page."""

from django import template
from django.utils.html import format_html

register = template.Library()


@register.simple_tag
def phrase_button(need, text):
    """One of the highlighted phrases in "We believe everyone deserves…". Clicking it highlights that need."""
    return format_html(
        '<button class="phrase" type="button" data-need="{}" aria-pressed="false">{}</button>', need, text
    )
