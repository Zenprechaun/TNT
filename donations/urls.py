from django.urls import path

from . import views

app_name = "donations"

urlpatterns = [
    path("donate/", views.donate, name="donate"),
    path("donate/receipt/<uuid:token>/", views.receipt, name="receipt"),
    path("donate/monthly/", views.manage, name="manage"),
    path("donate/stripe/webhook/", views.webhook, name="webhook"),
]
