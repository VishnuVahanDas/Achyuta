import datetime
import uuid
from contextlib import contextmanager
from decimal import Decimal

import pytest
from django.apps import apps
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import IntegrityError, connection, transaction

from catalog.models import Category, Merchant, Tag
from core.fields import MoneyField
from core.models import Workspace, WorkspaceModel
from ledger.models import (
    Account,
    Attachment,
    AuditLog,
    Book,
    LineItem,
    PaymentApp,
    Person,
    Posting,
    Transaction,
)

pytestmark = pytest.mark.django_db

TODAY = datetime.date(2026, 11, 1)


def make_account(workspace, name, type="bank", **kwargs):
    return Account.objects.create(workspace=workspace, name=name, type=type, **kwargs)


def make_transaction(workspace, status="confirmed", postings=(), **kwargs):
    kwargs.setdefault("kind", "spend")
    txn = Transaction.objects.create(workspace=workspace, date=TODAY, status=status, **kwargs)
    for account, amount in postings:
        Posting.objects.create(
            workspace=workspace, transaction=txn, account=account, amount=Decimal(amount)
        )
    return txn


@contextmanager
def refused_as_unbalanced():
    """The block must fail the commit-time balance check. Its writes are rolled back."""
    with pytest.raises(IntegrityError, match="sum to zero"), transaction.atomic():
        yield
        connection.check_constraints()  # run the deferred checks now, as a commit would


@pytest.fixture
def sbi(workspace):
    return make_account(workspace, "SBI")


@pytest.fixture
def expenses(workspace):
    return make_account(workspace, "Expenses", type="expense")


# --- Shape shared by every model ---


OWNED_MODELS = [
    *apps.get_app_config("ledger").get_models(),
    *apps.get_app_config("catalog").get_models(),
]


@pytest.mark.parametrize("model", OWNED_MODELS, ids=lambda m: m.__name__)
def test_every_model_has_a_workspace_and_timestamps(model):
    assert issubclass(model, WorkspaceModel)
    field_names = {f.name for f in model._meta.get_fields()}
    assert {"workspace", "created_at", "updated_at"} <= field_names


@pytest.mark.parametrize(
    ("model", "field"),
    [(Account, "opening_balance"), (Posting, "amount"), (LineItem, "amount")],
)
def test_money_is_decimal_with_two_places(model, field):
    money = model._meta.get_field(field)

    assert isinstance(money, MoneyField)
    assert money.decimal_places == 2


def test_amounts_round_trip_as_exact_decimals(workspace, sbi, expenses):
    txn = make_transaction(workspace, postings=[(expenses, "0.10"), (sbi, "-0.10")])

    amounts = [p.amount for p in txn.postings.all()]

    assert amounts == [Decimal("0.10"), Decimal("-0.10")]
    assert all(isinstance(a, Decimal) for a in amounts)


# --- Accounts, books, people, payment apps ---


def test_account_defaults(sbi):
    sbi.refresh_from_db()

    assert sbi.opening_balance == Decimal("0.00")
    assert sbi.track_balance is True
    assert sbi.is_active is True
    assert sbi.book is None


def test_all_eleven_account_types_exist():
    assert set(Account.Type.values) == {
        "bank", "cash", "card", "wallet", "fd", "proxy",
        "person", "fund", "capital", "income", "expense",
    }  # fmt: skip


def test_proxy_account_never_tracks_a_balance(workspace):
    father = Person.objects.create(workspace=workspace, name="Father")

    proxy = make_account(workspace, "Father's SBI", "proxy", person=father, track_balance=False)
    assert proxy.track_balance is False

    with pytest.raises(IntegrityError, match="account_proxy_not_tracked"), transaction.atomic():
        make_account(workspace, "Father's HDFC", "proxy", person=father, track_balance=True)


@pytest.mark.parametrize("type", ["proxy", "person"])
def test_proxy_and_person_accounts_need_a_person(workspace, type):
    with pytest.raises(IntegrityError, match="account_person_required"), transaction.atomic():
        make_account(workspace, "Nobody", type, track_balance=False)


def test_one_person_can_have_several_ledgers(workspace):
    brajesh = Person.objects.create(workspace=workspace, name="Brajesh")
    make_account(workspace, "Brajesh (Personal)", "person", person=brajesh)
    make_account(workspace, "Brajesh (Vishnu Wings)", "person", person=brajesh)

    assert brajesh.accounts.count() == 2


def test_names_are_unique_per_workspace_only(workspace, other_workspace, sbi):
    Book.objects.create(workspace=workspace, name="Personal")
    Person.objects.create(workspace=workspace, name="Ramesh")

    make_account(other_workspace, "SBI")
    Book.objects.create(workspace=other_workspace, name="Personal")
    Person.objects.create(workspace=other_workspace, name="Ramesh")

    with pytest.raises(IntegrityError), transaction.atomic():
        make_account(workspace, "SBI")
    with pytest.raises(IntegrityError), transaction.atomic():
        Book.objects.create(workspace=workspace, name="Personal")
    with pytest.raises(IntegrityError), transaction.atomic():
        Person.objects.create(workspace=workspace, name="Ramesh")


def test_payment_app_links_a_default_bank_and_others(workspace, sbi):
    hdfc = make_account(workspace, "HDFC")
    gpay = PaymentApp.objects.create(workspace=workspace, name="GPay", default_account=hdfc)
    gpay.other_accounts.add(sbi)

    assert gpay.default_account == hdfc
    assert list(gpay.other_accounts.all()) == [sbi]
    assert list(sbi.other_apps.all()) == [gpay]


def test_links_across_workspaces_fail_validation(workspace, other_workspace):
    their_book = Book.objects.create(workspace=other_workspace, name="Personal")
    account = Account(workspace=workspace, name="SBI", type="bank", book=their_book)

    with pytest.raises(ValidationError, match="different workspace"):
        account.full_clean()


# --- Transactions ---


def test_transaction_defaults_to_draft_with_its_own_client_uuid(workspace):
    first = Transaction.objects.create(workspace=workspace, date=TODAY, kind="spend")
    second = Transaction.objects.create(workspace=workspace, date=TODAY, kind="spend")

    assert first.status == "draft"
    assert isinstance(first.client_uuid, uuid.UUID)
    assert first.client_uuid != second.client_uuid


def test_client_uuid_is_unique_so_a_retried_entry_cannot_duplicate(workspace):
    client_uuid = uuid.uuid4()
    Transaction.objects.create(
        workspace=workspace, date=TODAY, kind="spend", client_uuid=client_uuid
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        Transaction.objects.create(
            workspace=workspace, date=TODAY, kind="spend", client_uuid=client_uuid
        )


def test_payment_modes_match_the_design():
    assert [label for _, label in Transaction.Mode.choices] == [
        "UPI", "NEFT", "IMPS", "RTGS", "NetBanking", "Cash", "Card", "Cheque",
    ]  # fmt: skip


def test_transaction_carries_its_details(workspace, sbi, user):
    food = Category.objects.create(workspace=workspace, name="Food", kind="expense")
    phonepe = PaymentApp.objects.create(workspace=workspace, name="PhonePe", default_account=sbi)
    blinkit = Merchant.objects.create(workspace=workspace, name="Blinkit", default_category=food)
    personal = Book.objects.create(workspace=workspace, name="Personal")
    friend = Person.objects.create(workspace=workspace, name="Friend")
    tag = Tag.objects.create(workspace=workspace, name="kartik-yatra")

    txn = Transaction.objects.create(
        workspace=workspace,
        date=TODAY,
        kind="spend",
        description="Groceries",
        merchant=blinkit,
        payment_app=phonepe,
        mode="upi",
        utr="430112345678",
        book=personal,
        on_behalf_of=friend,
        created_by=user,
    )
    txn.tags.add(tag)
    txn.refresh_from_db()

    assert (txn.merchant, txn.payment_app, txn.book) == (blinkit, phonepe, personal)
    assert (txn.on_behalf_of, txn.created_by) == (friend, user)
    assert txn.get_mode_display() == "UPI"
    assert list(tag.transactions.all()) == [txn]


def test_newest_transactions_come_first(workspace):
    older = Transaction.objects.create(
        workspace=workspace, date=TODAY - datetime.timedelta(days=1), kind="spend"
    )
    newer = Transaction.objects.create(workspace=workspace, date=TODAY, kind="spend")

    assert list(Transaction.objects.all()) == [newer, older]


# --- Integrity rule 1: a confirmed transaction's postings sum to zero ---


def test_confirmed_balanced_transaction_is_accepted(workspace, sbi, expenses):
    txn = make_transaction(workspace, postings=[(expenses, "619.00"), (sbi, "-619.00")])

    connection.check_constraints()

    assert sum(p.amount for p in txn.postings.all()) == 0


def test_confirmed_unbalanced_transaction_is_refused(workspace, sbi, expenses):
    with refused_as_unbalanced():
        make_transaction(workspace, postings=[(expenses, "619.00"), (sbi, "-600.00")])


def test_a_one_paisa_gap_is_refused(workspace, sbi, expenses):
    with refused_as_unbalanced():
        make_transaction(workspace, postings=[(expenses, "619.00"), (sbi, "-618.99")])


def test_confirmed_transaction_without_postings_is_refused(workspace):
    with refused_as_unbalanced():
        make_transaction(workspace)


def test_confirmed_transaction_with_one_posting_is_refused(workspace, sbi):
    with refused_as_unbalanced():
        make_transaction(workspace, postings=[(sbi, "-619.00")])


def test_draft_may_be_unbalanced(workspace, sbi):
    make_transaction(workspace, status="draft", postings=[(sbi, "-619.00")])

    connection.check_constraints()


def test_unbalanced_draft_cannot_be_confirmed(workspace, sbi):
    draft = make_transaction(workspace, status="draft", postings=[(sbi, "-619.00")])

    with refused_as_unbalanced():
        draft.status = "confirmed"
        draft.save()


def test_balanced_draft_can_be_confirmed(workspace, sbi, expenses):
    draft = make_transaction(
        workspace, status="draft", postings=[(expenses, "619.00"), (sbi, "-619.00")]
    )

    draft.status = "confirmed"
    draft.save()

    connection.check_constraints()


def test_confirmed_transaction_cannot_be_edited_out_of_balance(workspace, sbi, expenses):
    txn = make_transaction(workspace, postings=[(expenses, "619.00"), (sbi, "-619.00")])
    posting = txn.postings.get(account=sbi)

    with refused_as_unbalanced():
        posting.amount = Decimal("-500.00")
        posting.save()
    with refused_as_unbalanced():
        Posting.objects.filter(pk=posting.pk).update(amount=Decimal("-500.00"))
    with refused_as_unbalanced():
        posting.delete()
    with refused_as_unbalanced():
        Posting.objects.create(
            workspace=workspace, transaction=txn, account=sbi, amount=Decimal("1.00")
        )


def test_moving_a_posting_checks_the_transaction_it_left(workspace, sbi, expenses):
    txn = make_transaction(workspace, postings=[(expenses, "619.00"), (sbi, "-619.00")])
    draft = make_transaction(workspace, status="draft")

    with refused_as_unbalanced():
        txn.postings.filter(account=sbi).update(transaction=draft)


def test_confirmed_transaction_can_be_rebalanced_in_one_go(workspace, sbi, expenses):
    txn = make_transaction(workspace, postings=[(expenses, "619.00"), (sbi, "-619.00")])

    txn.postings.filter(account=expenses).update(amount=Decimal("700.00"))
    txn.postings.filter(account=sbi).update(amount=Decimal("-700.00"))

    connection.check_constraints()


def test_deleting_a_transaction_removes_its_postings(workspace, sbi, expenses):
    txn = make_transaction(workspace, postings=[(expenses, "619.00"), (sbi, "-619.00")])

    txn.delete()
    connection.check_constraints()

    assert Posting.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_unbalanced_transaction_fails_at_a_real_commit(workspace, sbi, expenses):
    with pytest.raises(IntegrityError, match="sum to zero"), transaction.atomic():
        make_transaction(workspace, postings=[(expenses, "619.00"), (sbi, "-600.00")])

    assert Transaction.objects.count() == 0


def test_posting_amount_cannot_be_zero(workspace, sbi):
    draft = make_transaction(workspace, status="draft")

    with pytest.raises(IntegrityError, match="posting_amount_not_zero"), transaction.atomic():
        Posting.objects.create(workspace=workspace, transaction=draft, account=sbi, amount=0)


# --- Worked examples from the design ---


def test_blinkit_purchase_is_one_bank_debit_across_two_categories(workspace, sbi, expenses):
    food = Category.objects.create(workspace=workspace, name="Food", kind="expense")
    fruits = Category.objects.create(
        workspace=workspace, name="Fruits", kind="expense", parent=food
    )
    assets = Category.objects.create(workspace=workspace, name="Assets", kind="expense")
    accessories = Category.objects.create(
        workspace=workspace, name="Accessories", kind="expense", parent=assets
    )
    txn = Transaction.objects.create(
        workspace=workspace, date=TODAY, kind="spend", status="confirmed"
    )
    for account, amount, category in [
        (sbi, "-619.00", None),
        (expenses, "120.00", fruits),
        (expenses, "499.00", accessories),
    ]:
        Posting.objects.create(
            workspace=workspace,
            transaction=txn,
            account=account,
            amount=Decimal(amount),
            category=category,
        )
    LineItem.objects.create(
        workspace=workspace,
        transaction=txn,
        name="Apple",
        amount=Decimal("120.00"),
        category=fruits,
    )
    LineItem.objects.create(
        workspace=workspace,
        transaction=txn,
        name="Charger",
        amount=Decimal("499.00"),
        category=accessories,
    )

    connection.check_constraints()

    assert txn.postings.filter(account=sbi).count() == 1
    assert sum(item.amount for item in txn.line_items.all()) == Decimal("619.00")
    assert txn.line_items.get(name="Apple").qty == Decimal("1.000")
    assert {p.category for p in txn.postings.exclude(category=None)} == {fruits, accessories}


def test_paying_ramesh_from_fathers_account_posts_no_amount_to_the_proxy(workspace):
    father = Person.objects.create(workspace=workspace, name="Father")
    ramesh = Person.objects.create(workspace=workspace, name="Ramesh")
    fathers_sbi = make_account(
        workspace, "Father's SBI", "proxy", person=father, track_balance=False
    )
    father_ledger = make_account(workspace, "Father", "person", person=father)
    ramesh_ledger = make_account(workspace, "Ramesh", "person", person=ramesh)

    txn = Transaction.objects.create(
        workspace=workspace,
        date=TODAY,
        kind="lend",
        status="confirmed",
        proxy_account=fathers_sbi,
    )
    Posting.objects.create(
        workspace=workspace,
        transaction=txn,
        account=ramesh_ledger,
        amount=Decimal("10000.00"),
        person=ramesh,
        funding_owner=father,
    )
    Posting.objects.create(
        workspace=workspace,
        transaction=txn,
        account=father_ledger,
        amount=Decimal("-10000.00"),
        person=father,
    )

    connection.check_constraints()

    assert txn.proxy_account == fathers_sbi
    assert fathers_sbi.postings.count() == 0
    assert list(father.funded_postings.all()) == [txn.postings.get(account=ramesh_ledger)]


# --- Attachments, audit log, deletion ---


def test_attachment_is_stored_privately_with_no_public_url(workspace, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    txn = make_transaction(workspace, status="draft")

    attachment = Attachment.objects.create(
        workspace=workspace,
        transaction=txn,
        kind="receipt",
        file=ContentFile(b"order", name="Blinkit Order.PNG"),
    )

    stored = tmp_path / attachment.file.name
    assert stored.read_bytes() == b"order"
    assert stored.parent == tmp_path / f"workspace_{workspace.pk}" / "attachments"
    assert stored.suffix == ".png"
    assert "Blinkit" not in attachment.file.name
    with pytest.raises(ValueError, match="no public URL"):
        _ = attachment.file.url


def test_audit_log_records_a_field_change_on_any_object(workspace, sbi, user):
    entry = AuditLog.objects.create(
        workspace=workspace,
        target=sbi,
        action="update",
        field="name",
        old_value="SBI",
        new_value="SBI Savings",
        actor=user,
    )
    entry.refresh_from_db()

    assert entry.target == sbi
    assert entry.created_at is not None
    assert (entry.old_value, entry.new_value) == ("SBI", "SBI Savings")


def test_accounts_in_use_cannot_be_deleted(workspace, sbi, expenses):
    make_transaction(workspace, postings=[(expenses, "619.00"), (sbi, "-619.00")])

    with pytest.raises(IntegrityError), transaction.atomic():
        sbi.delete()


def test_deleting_a_workspace_removes_only_its_own_data(workspace, other_workspace, sbi, expenses):
    make_transaction(workspace, postings=[(expenses, "619.00"), (sbi, "-619.00")])
    theirs = make_account(other_workspace, "SBI")

    workspace.delete()
    connection.check_constraints()

    assert list(Workspace.objects.all()) == [other_workspace]
    assert list(Account.objects.all()) == [theirs]
    assert Transaction.objects.count() == 0
