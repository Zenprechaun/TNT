from django.urls import path

from . import views

app_name = "mailboxes"

urlpatterns = [
    path("dashboard/manage/google/callback/", views.callback, name="callback"),
]
