import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

pytestmark = pytest.mark.django_db

TABS = ["home", "entries", "people", "deals", "more"]
PAGES = [*TABS, "entry_add"]


def test_user_model_is_the_custom_one():
    assert get_user_model()._meta.label == "core.User"


@pytest.mark.parametrize("name", PAGES)
def test_pages_redirect_anonymous_visitors_to_login(client, name):
    url = reverse(name)

    response = client.get(url)

    assert response.status_code == 302
    assert response["Location"] == f"{reverse('login')}?next={url}"


@pytest.mark.parametrize("name", PAGES)
def test_pages_render_with_navigation_when_logged_in(client, user, name):
    client.force_login(user)

    response = client.get(reverse(name))

    assert response.status_code == 200
    html = response.content.decode()
    for tab in TABS:
        assert f'href="{reverse(tab)}"' in html
    assert 'aria-label="Add entry"' in html
    assert f'href="{reverse("entry_add")}"' in html


@pytest.mark.parametrize("name", TABS)
def test_only_the_current_tab_is_marked_active(client, user, name):
    client.force_login(user)

    html = client.get(reverse(name)).content.decode()

    assert html.count('aria-current="page"') == 1
    assert f'href="{reverse(name)}" aria-current="page"' in html


def test_login_page_has_no_navigation(client):
    response = client.get(reverse("login"))

    assert response.status_code == 200
    assert 'aria-label="Main"' not in response.content.decode()


def test_login_with_correct_password_goes_home(client, user):
    response = client.post(reverse("login"), {"username": "vipul", "password": "pw-for-tests"})

    assert response.status_code == 302
    assert response["Location"] == reverse("home")


def test_login_with_wrong_password_shows_an_error(client, user):
    response = client.post(reverse("login"), {"username": "vipul", "password": "wrong"})

    assert response.status_code == 200
    assert 'role="alert"' in response.content.decode()


def test_logout_is_post_only_and_ends_the_session(client, user):
    client.force_login(user)

    assert client.get(reverse("logout")).status_code == 405
    response = client.post(reverse("logout"))

    assert response["Location"] == reverse("login")
    assert client.get(reverse("home")).status_code == 302


def test_more_page_shows_the_workspace(client, user):
    client.force_login(user)

    html = client.get(reverse("more")).content.decode()

    assert "vipul · INR" in html
