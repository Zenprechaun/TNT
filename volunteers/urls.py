from django.urls import path

from . import views

app_name = "volunteers"

urlpatterns = [
    path("", views.start, name="start"),
    path("<slug:slug>/", views.signup, name="signup"),
    path("<slug:slug>/spots.json", views.spots, name="spots"),
    path("<slug:slug>/confirmed/<uuid:token>/", views.confirmed, name="confirmed"),
    path("<slug:slug>/confirmed/<uuid:token>/shifts.ics", views.calendar_file, name="calendar"),
]
