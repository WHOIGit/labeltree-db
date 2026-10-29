from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("login/", auth_views.LoginView.as_view(template_name="webapp/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("me/", views.me, name="me"),
    path("orgs/<slug:org_id>/", views.org_page, name="org"),
    path("trees/<slug:tree_id>/", views.tree_page, name="tree"),
    path("trees/<slug:tree_id>/drafts/", views.drafts_page, name="drafts"),
    path("changesets/<int:cs>/", views.review_page, name="review"),
    path("changesets/<int:cs>/edit/", views.edit_page, name="edit"),
    path("nodes/<int:node_id>/", views.node_page, name="node"),
]
