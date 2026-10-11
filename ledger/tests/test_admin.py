import datetime
from decimal import Decimal

import pytest
from django.contrib import admin
from django.core.files.base import ContentFile
from django.urls import reverse

from core.models import WorkspaceModel
from core.services import workspace_for
from ledger.models import Account, Attachment, AuditLog, Book, Posting, Transaction

pytestmark = pytest.mark.django_db

OWNED_MODELS = [m for m in admin.site._registry if issubclass(m, WorkspaceModel)]


def admin_url(model, page, *args):
    return reverse(f"admin:{model._meta.app_label}_{model._meta.model_name}_{page}", args=args)


@pytest.fixture
def my_workspace(admin_user):
    return workspace_for(admin_user)


def test_all_twelve_models_are_registered():
    assert {m.__name__ for m in OWNED_MODELS} == {
        "Account", "PaymentApp", "Book", "Person", "Transaction", "Posting",
        "LineItem", "Attachment", "AuditLog", "Category", "Tag", "Merchant",
    }  # fmt: skip


@pytest.mark.parametrize("model", OWNED_MODELS, ids=lambda m: m.__name__)
def test_list_and_add_pages_load_with_a_workspace_filter(admin_client, model):
    changelist = admin_client.get(admin_url(model, "changelist"))

    assert changelist.status_code == 200
    assert "workspace" in changelist.context["cl"].list_filter
    expected = 403 if model is AuditLog else 200
    assert admin_client.get(admin_url(model, "add")).status_code == expected


def test_list_can_be_filtered_to_one_workspace(admin_client, my_workspace, other_workspace):
    Book.objects.create(workspace=my_workspace, name="Mine")
    Book.objects.create(workspace=other_workspace, name="Theirs")

    response = admin_client.get(
        admin_url(Book, "changelist"), {"workspace__id__exact": other_workspace.pk}
    )

    assert [b.name for b in response.context["cl"].result_list] == ["Theirs"]


def test_change_page_offers_only_the_objects_own_workspace(
    admin_client, my_workspace, other_workspace
):
    Book.objects.create(workspace=my_workspace, name="Mine")
    theirs = Book.objects.create(workspace=other_workspace, name="Theirs")
    account = Account.objects.create(workspace=other_workspace, name="SBI", type="bank")

    response = admin_client.get(admin_url(Account, "change", account.pk))

    choices = response.context["adminform"].form.fields["book"].queryset
    assert list(choices) == [theirs]


def test_add_page_defaults_to_the_admins_own_workspace(admin_client, my_workspace, other_workspace):
    mine = Book.objects.create(workspace=my_workspace, name="Mine")
    theirs = Book.objects.create(workspace=other_workspace, name="Theirs")

    own = admin_client.get(admin_url(Account, "add")).context["adminform"].form
    picked = admin_client.get(
        admin_url(Account, "add"), {"workspace": other_workspace.pk}
    ).context["adminform"].form  # fmt: skip

    assert own.initial["workspace"] == my_workspace
    assert list(own.fields["book"].queryset) == [mine]
    assert list(picked.fields["book"].queryset) == [theirs]


def test_saving_a_link_into_another_workspace_is_rejected(
    admin_client, my_workspace, other_workspace
):
    theirs = Book.objects.create(workspace=other_workspace, name="Theirs")

    response = admin_client.post(
        admin_url(Account, "add"),
        {
            "workspace": my_workspace.pk,
            "name": "SBI",
            "type": "bank",
            "book": theirs.pk,
            "opening_balance": "0.00",
            "track_balance": "on",
            "is_active": "on",
        },
    )

    assert response.status_code == 200
    assert "book" in response.context["adminform"].form.errors
    assert not Account.objects.exists()


def test_proxy_account_that_tracks_a_balance_gets_a_form_error(admin_client, my_workspace):
    response = admin_client.post(
        admin_url(Account, "add"),
        {
            "workspace": my_workspace.pk,
            "name": "Father's SBI",
            "type": "proxy",
            "opening_balance": "0.00",
            "track_balance": "on",
        },
    )

    errors = response.context["adminform"].form.non_field_errors()
    assert "A proxy account cannot track a balance." in errors
    assert "Person and proxy accounts need a person." in errors


def transaction_form(workspace, status, postings):
    data = {
        "workspace": workspace.pk,
        "date": "2026-11-01",
        "kind": "spend",
        "status": status,
        "postings-TOTAL_FORMS": len(postings),
        "postings-INITIAL_FORMS": 0,
        "line_items-TOTAL_FORMS": 0,
        "line_items-INITIAL_FORMS": 0,
        "attachments-TOTAL_FORMS": 0,
        "attachments-INITIAL_FORMS": 0,
    }
    for i, (account, amount) in enumerate(postings):
        data[f"postings-{i}-account"] = account.pk
        data[f"postings-{i}-amount"] = amount
    return data


@pytest.fixture
def accounts(my_workspace):
    return (
        Account.objects.create(workspace=my_workspace, name="SBI", type="bank"),
        Account.objects.create(workspace=my_workspace, name="Expenses", type="expense"),
    )


def test_balanced_transaction_saves_with_postings_in_its_workspace(
    admin_client, my_workspace, accounts
):
    sbi, expenses = accounts

    response = admin_client.post(
        admin_url(Transaction, "add"),
        transaction_form(my_workspace, "confirmed", [(expenses, "619.00"), (sbi, "-619.00")]),
    )

    assert response.status_code == 302
    txn = Transaction.objects.get()
    assert [p.amount for p in txn.postings.all()] == [Decimal("619.00"), Decimal("-619.00")]
    assert {p.workspace for p in txn.postings.all()} == {my_workspace}


def test_unbalanced_confirmed_transaction_gets_a_form_error(admin_client, my_workspace, accounts):
    sbi, expenses = accounts

    response = admin_client.post(
        admin_url(Transaction, "add"),
        transaction_form(my_workspace, "confirmed", [(expenses, "619.00"), (sbi, "-600.00")]),
    )

    assert response.status_code == 200
    assert "sum to zero" in response.content.decode()
    assert not Transaction.objects.exists()


def test_unbalanced_draft_saves(admin_client, my_workspace, accounts):
    sbi, _ = accounts

    response = admin_client.post(
        admin_url(Transaction, "add"),
        transaction_form(my_workspace, "draft", [(sbi, "-619.00")]),
    )

    assert response.status_code == 302
    assert Posting.objects.count() == 1


def test_attachment_pages_render_without_a_file_link(
    admin_client, my_workspace, settings, tmp_path
):
    settings.MEDIA_ROOT = tmp_path
    txn = Transaction.objects.create(
        workspace=my_workspace, date=datetime.date(2026, 11, 1), kind="spend"
    )
    attachment = Attachment.objects.create(
        workspace=my_workspace, transaction=txn, file=ContentFile(b"x", name="bill.pdf")
    )

    for url in [
        admin_url(Attachment, "changelist"),
        admin_url(Attachment, "change", attachment.pk),
        admin_url(Transaction, "change", txn.pk),
    ]:
        assert admin_client.get(url).status_code == 200
