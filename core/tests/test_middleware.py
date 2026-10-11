import pytest
from django.urls import reverse

from core.models import Workspace

pytestmark = pytest.mark.django_db


def test_anonymous_request_has_no_workspace(client):
    response = client.get(reverse("login"))

    assert response.wsgi_request.workspace is None
    assert Workspace.objects.count() == 0


def test_logged_in_request_carries_the_users_workspace(client, user):
    client.force_login(user)

    response = client.get(reverse("home"))

    assert response.wsgi_request.workspace.owner == user


def test_users_never_share_a_workspace(client, user, other_user):
    client.force_login(user)
    mine = client.get(reverse("home")).wsgi_request.workspace
    client.force_login(other_user)
    theirs = client.get(reverse("home")).wsgi_request.workspace

    assert mine != theirs
    assert theirs.owner == other_user
