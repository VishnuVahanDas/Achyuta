import pytest


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(username="vipul", password="pw-for-tests")


@pytest.fixture
def other_user(django_user_model):
    return django_user_model.objects.create_user(username="friend", password="pw-for-tests")


@pytest.fixture
def workspace(user):
    from core.services import workspace_for

    return workspace_for(user)


@pytest.fixture
def other_workspace(other_user):
    from core.services import workspace_for

    return workspace_for(other_user)
