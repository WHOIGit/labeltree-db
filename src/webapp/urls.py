from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("login/", auth_views.LoginView.as_view(template_name="webapp/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("setup/", views.setup, name="setup"),
    path("me/", views.me, name="me"),
    path(
        "me/password/",
        auth_views.PasswordChangeView.as_view(
            template_name="webapp/password_change.html", success_url="/me/password/done/"
        ),
        name="password_change",
    ),
    path(
        "me/password/done/",
        auth_views.PasswordChangeDoneView.as_view(template_name="webapp/password_change_done.html"),
        name="password_change_done",
    ),
    path("orgs/<slug:org_id>/", views.org_page, name="org"),
    path("trees/<slug:tree_id>/", views.tree_page, name="tree"),
    path("trees/<slug:tree_id>/drafts/", views.drafts_page, name="drafts"),
    path("changesets/<int:cs>/", views.review_page, name="review"),
    path("changesets/<int:cs>/edit/", views.edit_page, name="edit"),
    path("nodes/<int:node_id>/", views.node_page, name="node"),
]
