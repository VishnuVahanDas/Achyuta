import pytest
from django.utils import timezone

from core import services
from core.models import Workspace

pytestmark = pytest.mark.django_db


def test_workspace_for_creates_workspace_with_defaults(user):
    workspace = services.workspace_for(user)

    assert workspace.owner == user
    assert workspace.name == "vipul"
    assert workspace.currency == "INR"
    assert workspace.start_date == timezone.localdate()


def test_workspace_for_uses_full_name_when_set(user):
    user.first_name, user.last_name = "Vipul", "Kumar"
    user.save()

    assert services.workspace_for(user).name == "Vipul Kumar"


def test_workspace_for_returns_the_same_workspace_every_time(user):
    first = services.workspace_for(user)
    second = services.workspace_for(user)

    assert first == second
    assert Workspace.objects.count() == 1


def test_each_user_gets_their_own_workspace(user, other_user):
    assert services.workspace_for(user) != services.workspace_for(other_user)
    assert Workspace.objects.count() == 2
