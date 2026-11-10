from django.contrib.auth.views import LogoutView
from django.urls import path

from . import manage, views

app_name = "accounts"

urlpatterns = [
    path("accounts/login/", views.login_view, name="login"),
    path("accounts/register/", views.register_view, name="register"),
    path("accounts/logout/", LogoutView.as_view(), name="logout"),
    path("accounts/password/forgot/", views.ForgotPasswordView.as_view(), name="password_forgot"),
    path("accounts/password/forgot/sent/", views.ForgotPasswordSentView.as_view(), name="password_reset_sent"),
    path("accounts/password/reset/<uidb64>/<token>/", views.ResetPasswordView.as_view(),
         name="password_reset_confirm"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("dashboard/user/", views.user_dashboard, name="user_dashboard"),
    path("dashboard/admin/", views.admin_dashboard, name="admin_dashboard"),
    path("dashboard/admin/people/<int:user_id>/roles/", views.update_roles, name="update_roles"),
    path("dashboard/manage/", manage.manage, name="manage"),
    path("dashboard/manage/events/<int:pk>/roster.csv", manage.roster_csv, name="manage_roster"),
    path("dashboard/manage/donations-<int:year>.csv", manage.donations_csv, name="manage_donations_csv"),
]
