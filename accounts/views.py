"""Signing in, and the User's and Admin's dashboards."""

from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST

from .decorators import role_required
from .forms import LoginForm, RolesForm
from .models import Role
from .roles import dashboard_url_for, get_profile

User = get_user_model()

MISSING_DETAILS = gettext_lazy("Enter your email or username and your password.")


def _wants_json(request):
    """The login popup asks for JSON so it can show a mistake without reloading the page."""
    return "application/json" in request.headers.get("Accept", "")


def _safe_next(request):
    """A page on this site to return to after signing in, if one was asked for."""
    target = request.POST.get("next") or request.GET.get("next") or ""
    allowed = url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    )
    return target if target and allowed else ""


@require_http_methods(["GET", "POST"])
@sensitive_post_parameters("password")
@csrf_protect
@never_cache
def login_view(request):
    """Signs people in from the login popup or the full login page."""
    next_url = _safe_next(request)
    if request.method == "GET" and request.user.is_authenticated:
        return redirect(next_url or dashboard_url_for(request.user))

    form = LoginForm(request, data=request.POST or None)
    error = ""
    if request.method == "POST":
        if form.is_valid():
            user = form.get_user()
            auth_login(request, user)
            if not form.cleaned_data.get("remember"):
                request.session.set_expiry(0)  # sign out when the browser closes
            target = next_url or dashboard_url_for(user)
            if _wants_json(request):
                return JsonResponse({"ok": True, "redirect": target})
            return redirect(target)
        problems = form.non_field_errors()
        error = problems[0] if problems else MISSING_DETAILS
        if _wants_json(request):
            return JsonResponse({"ok": False, "message": error}, status=400)

    return render(request, "accounts/login.html", {"form": form, "error": error, "next": next_url})


@login_required
def dashboard(request):
    """Sends people to the dashboard that matches their roles."""
    return redirect(dashboard_url_for(request.user))


@login_required
def user_dashboard(request):
    profile = get_profile(request.user)
    return render(request, "accounts/dashboard_user.html", {"roles": profile.roles.all(), "dash": "user"})


@role_required(Role.ADMIN)
def admin_dashboard(request):
    query = request.GET.get("q", "").strip()
    people = User.objects.order_by("username").select_related("profile").prefetch_related("profile__roles")
    if query:
        people = people.filter(
            Q(username__icontains=query)
            | Q(email__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
        )
    page = Paginator(people, 25).get_page(request.GET.get("page"))

    rows = []
    for person in page:
        profile = getattr(person, "profile", None) or get_profile(person)
        rows.append(
            {
                "person": person,
                "role_ids": {role.pk for role in profile.roles.all()},
                "is_self": person.pk == request.user.pk,
            }
        )

    since = timezone.now() - timedelta(days=30)
    stats = [
        (_("People"), User.objects.count()),
        (_("Admins"), User.objects.filter(profile__roles__slug=Role.ADMIN).distinct().count()),
        (_("Joined in the last 30 days"), User.objects.filter(date_joined__gte=since).count()),
        (_("Signed in during the last 30 days"), User.objects.filter(last_login__gte=since).count()),
    ]
    return render(
        request,
        "accounts/dashboard_admin.html",
        {"rows": rows, "roles": Role.objects.all(), "page": page, "query": query, "stats": stats, "dash": "admin"},
    )


@role_required(Role.ADMIN)
@require_POST
def update_roles(request, user_id):
    """Saves the roles an admin ticked for one person on the Admin's Dashboard."""
    person = get_object_or_404(User, pk=user_id)
    profile = get_profile(person)
    name = person.get_full_name() or person.get_username()
    form = RolesForm(request.POST)

    if not form.is_valid():
        messages.error(request, _("Roles for %(name)s weren't changed. Choose at least one role.") % {"name": name})
    else:
        roles = list(form.cleaned_data["roles"])
        removes_own_admin = person.pk == request.user.pk and all(role.slug != Role.ADMIN for role in roles)
        if removes_own_admin:
            messages.error(request, _("You can't remove your own Admin role. Another admin can do that for you."))
        else:
            profile.roles.set(roles)
            role_names = ", ".join(str(role.display_name) for role in roles)
            messages.success(request, _("Saved roles for %(name)s: %(roles)s.") % {"name": name, "roles": role_names})

    params = {key: request.POST[key] for key in ("q", "page") if request.POST.get(key)}
    url = reverse("accounts:admin_dashboard")
    if params:
        url = f"{url}?{urlencode(params)}"
    return redirect(f"{url}#person-{person.pk}")
