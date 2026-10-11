import datetime
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.models import Sum
from django.utils import timezone

from catalog.models import Category, Merchant, Tag
from ledger import services
from ledger.models import Account, AuditLog, Book, PaymentApp, Person, Posting, Transaction
from ledger.services import Item

pytestmark = pytest.mark.django_db

D = Decimal
NOV_1 = datetime.date(2026, 11, 1)
NOV_5 = datetime.date(2026, 11, 5)


def account(workspace, name, type="bank", **kwargs):
    return Account.objects.create(workspace=workspace, name=name, type=type, **kwargs)


def category(workspace, name, parent=None, kind="expense"):
    return Category.objects.create(workspace=workspace, name=name, kind=kind, parent=parent)


def person(workspace, name):
    return Person.objects.create(workspace=workspace, name=name)


def postings(txn):
    """The transaction's postings as {account name: amount}, for one posting per account."""
    return {p.account.name: p.amount for p in txn.postings.select_related("account")}


def expense_total(workspace):
    total = Posting.objects.filter(workspace=workspace, account__type="expense").aggregate(
        total=Sum("amount")
    )["total"]
    return total or D("0.00")


@pytest.fixture(autouse=True)
def balanced_at_commit():
    """After every test, run the database's own zero-sum check on what was saved."""
    yield
    connection.check_constraints()


@pytest.fixture
def sbi(workspace):
    return account(workspace, "SBI", opening_balance=D("50000.00"))


@pytest.fixture
def hdfc(workspace):
    return account(workspace, "HDFC", opening_balance=D("20000.00"))


@pytest.fixture
def cash(workspace):
    return account(workspace, "Cash", "cash")


@pytest.fixture
def phonepe(workspace, sbi):
    return PaymentApp.objects.create(workspace=workspace, name="PhonePe", default_account=sbi)


@pytest.fixture
def food(workspace):
    return category(workspace, "Food")


@pytest.fixture
def salary(workspace):
    return category(workspace, "Salary", kind="income")


@pytest.fixture
def ramesh(workspace):
    return person(workspace, "Ramesh")


# --- spend ---


def test_spend_debits_the_account_and_books_an_expense(workspace, sbi, food):
    txn = services.spend(workspace, amount=D("450.00"), account=sbi, category=food, date=NOV_1)

    assert postings(txn) == {"SBI": D("-450.00"), "Expenses": D("450.00")}
    assert (txn.kind, txn.status, txn.date) == ("spend", "confirmed", NOV_1)
    assert txn.postings.get(account__type="expense").category == food
    assert services.account_balance(sbi) == D("49550.00")


def test_spend_through_a_payment_app_resolves_its_default_bank(workspace, sbi, phonepe, food):
    txn = services.spend(workspace, amount=D("450.00"), payment_app=phonepe, category=food)

    assert postings(txn)["SBI"] == D("-450.00")
    assert txn.payment_app == phonepe
    assert txn.mode == "upi"


def test_spend_uses_the_passed_account_over_the_apps_default(workspace, phonepe, hdfc, food):
    phonepe.other_accounts.add(hdfc)

    txn = services.spend(
        workspace, amount=D("450.00"), payment_app=phonepe, account=hdfc, category=food
    )

    assert postings(txn) == {"HDFC": D("-450.00"), "Expenses": D("450.00")}


def test_spend_refuses_an_account_the_app_is_not_linked_to(workspace, phonepe, hdfc, food):
    with pytest.raises(ValidationError, match="not linked"):
        services.spend(
            workspace, amount=D("450.00"), payment_app=phonepe, account=hdfc, category=food
        )


def test_spend_needs_an_account_or_a_payment_app(workspace, food):
    with pytest.raises(ValidationError, match="account or a payment app"):
        services.spend(workspace, amount=D("450.00"), category=food)


def test_spend_without_a_category_is_a_draft_that_still_moves_the_money(workspace, sbi):
    txn = services.spend(workspace, amount=D("450.00"), account=sbi)

    assert txn.status == "draft"
    assert postings(txn) == {"SBI": D("-450.00"), "Expenses": D("450.00")}
    assert services.account_balance(sbi) == D("49550.00")
    assert services.account_balance(sbi, include_drafts=False) == D("50000.00")


def test_spend_defaults_to_today(workspace, sbi, food):
    txn = services.spend(workspace, amount=D("450.00"), account=sbi, category=food)

    assert txn.date == timezone.localdate()


def test_spend_saves_the_optional_details(workspace, sbi, food, user):
    blinkit = Merchant.objects.create(workspace=workspace, name="Blinkit")
    personal = Book.objects.create(workspace=workspace, name="Personal")
    tag = Tag.objects.create(workspace=workspace, name="bike")

    txn = services.spend(
        workspace,
        amount=D("450.00"),
        account=sbi,
        category=food,
        description="Groceries",
        merchant=blinkit,
        mode="card",
        utr="430112345678",
        book=personal,
        tags=[tag],
        created_by=user,
    )

    assert (txn.description, txn.merchant, txn.mode) == ("Groceries", blinkit, "card")
    assert (txn.utr, txn.book, txn.created_by) == ("430112345678", personal, user)
    assert list(txn.tags.all()) == [tag]


def test_spend_refuses_an_income_category(workspace, sbi, salary):
    with pytest.raises(ValidationError, match="not an expense category"):
        services.spend(workspace, amount=D("450.00"), account=sbi, category=salary)


def test_unknown_details_are_an_error(workspace, sbi, food):
    with pytest.raises(TypeError, match="notes"):
        services.spend(workspace, amount=D("450.00"), account=sbi, category=food, notes="x")


# --- spend_with_items ---


def test_blinkit_619_is_one_debit_split_into_fruits_and_accessories(workspace, phonepe, sbi, food):
    fruits = category(workspace, "Fruits", food)
    accessories = category(workspace, "Accessories", category(workspace, "Assets"))

    txn = services.spend_with_items(
        workspace,
        payment_app=phonepe,
        amount=D("619.00"),
        items=[
            Item("Apple", D("120.00"), fruits),
            Item("Charger", D("499.00"), accessories),
        ],
    )

    by_category = {p.category: p.amount for p in txn.postings.exclude(category=None)}
    assert by_category == {fruits: D("120.00"), accessories: D("499.00")}
    assert [p.amount for p in txn.postings.filter(account=sbi)] == [D("-619.00")]
    assert txn.postings.count() == 3
    assert [(i.name, i.amount, i.category) for i in txn.line_items.all()] == [
        ("Apple", D("120.00"), fruits),
        ("Charger", D("499.00"), accessories),
    ]
    assert txn.status == "confirmed"
    assert services.account_balance(sbi) == D("49381.00")
    assert expense_total(workspace) == D("619.00")


def test_items_in_the_same_category_share_one_expense_posting(workspace, sbi, food):
    txn = services.spend_with_items(
        workspace,
        account=sbi,
        items=[Item("Apple", D("120.00"), food, qty=2), Item("Milk", D("60.00"), food)],
    )

    assert postings(txn) == {"SBI": D("-180.00"), "Expenses": D("180.00")}
    assert txn.line_items.get(name="Apple").qty == D("2.000")
    assert txn.line_items.count() == 2


def test_items_must_add_up_to_the_bill_total(workspace, sbi, food):
    with pytest.raises(ValidationError, match="add up to 619.00, not 620.00"):
        services.spend_with_items(
            workspace,
            account=sbi,
            amount=D("620.00"),
            items=[Item("Apple", D("120.00"), food), Item("Charger", D("499.00"), food)],
        )
    assert not Transaction.objects.exists()


def test_an_item_without_a_category_makes_the_purchase_a_draft(workspace, sbi, food):
    txn = services.spend_with_items(
        workspace,
        account=sbi,
        items=[Item("Apple", D("120.00"), food), Item("Charger", D("499.00"))],
    )

    assert txn.status == "draft"
    assert postings(txn)["SBI"] == D("-619.00")


@pytest.mark.parametrize(
    ("items", "message"),
    [
        ([], "at least one item"),
        ([Item(" ", D("10.00"))], "needs a name"),
        ([Item("Apple", D("10.00"), qty=0)], "Quantity"),
        ([Item("Apple", D("0.00"))], "more than zero"),
    ],
)
def test_bad_items_are_refused(workspace, sbi, items, message):
    with pytest.raises(ValidationError, match=message):
        services.spend_with_items(workspace, account=sbi, items=items)


# --- receive ---


def test_receive_credits_the_account_and_books_income(workspace, sbi, salary):
    txn = services.receive(workspace, amount=D("80000.00"), account=sbi, category=salary)

    assert postings(txn) == {"SBI": D("80000.00"), "Income": D("-80000.00")}
    assert (txn.kind, txn.status) == ("receive", "confirmed")
    assert txn.postings.get(account__type="income").category == salary
    assert services.account_balance(sbi) == D("130000.00")


def test_receive_without_a_category_is_a_draft(workspace, phonepe):
    txn = services.receive(workspace, amount=D("500.00"), payment_app=phonepe)

    assert txn.status == "draft"
    assert postings(txn)["SBI"] == D("500.00")


def test_receive_refuses_an_expense_category(workspace, sbi, food):
    with pytest.raises(ValidationError, match="not an income category"):
        services.receive(workspace, amount=D("500.00"), account=sbi, category=food)


# --- transfer ---


def test_atm_withdrawal_moves_money_but_is_not_an_expense(workspace, sbi, cash, food):
    services.spend(workspace, amount=D("450.00"), account=sbi, category=food)

    txn = services.transfer(workspace, amount=D("2000.00"), from_account=sbi, to_account=cash)

    assert postings(txn) == {"SBI": D("-2000.00"), "Cash": D("2000.00")}
    assert txn.kind == "transfer"
    assert not txn.postings.filter(account__type__in=["expense", "income"]).exists()
    assert expense_total(workspace) == D("450.00")
    assert services.account_balance(sbi) == D("47550.00")
    assert services.account_balance(cash) == D("2000.00")


def test_transfer_to_a_fixed_deposit_and_card_bill_are_allowed(workspace, sbi):
    fd = account(workspace, "FD-SBI-01", "fd")
    card = account(workspace, "HDFC Card", "card")
    services.spend(workspace, amount=D("3000.00"), account=card)

    services.transfer(workspace, amount=D("10000.00"), from_account=sbi, to_account=fd)
    services.transfer(workspace, amount=D("3000.00"), from_account=sbi, to_account=card)

    assert services.account_balance(fd) == D("10000.00")
    assert services.account_balance(card) == D("0.00")
    assert services.account_balance(sbi) == D("37000.00")


def test_transfer_resolves_the_source_from_a_payment_app(workspace, phonepe, hdfc):
    txn = services.transfer(workspace, amount=D("1000.00"), payment_app=phonepe, to_account=hdfc)

    assert postings(txn) == {"SBI": D("-1000.00"), "HDFC": D("1000.00")}


def test_transfer_needs_two_different_own_accounts(workspace, sbi, ramesh):
    ledger = account(workspace, "Ramesh", "person", person=ramesh)

    with pytest.raises(ValidationError, match="two different"):
        services.transfer(workspace, amount=D("100.00"), from_account=sbi, to_account=sbi)
    with pytest.raises(ValidationError, match="cannot be used"):
        services.transfer(workspace, amount=D("100.00"), from_account=sbi, to_account=ledger)


# --- lend, borrow, settle ---


def test_lend_then_partial_and_full_return(workspace, sbi, ramesh):
    lent = services.lend(workspace, person=ramesh, amount=D("5000.00"), account=sbi, date=NOV_1)

    assert postings(lent) == {"SBI": D("-5000.00"), "Ramesh": D("5000.00")}
    assert lent.kind == "lend"
    assert lent.postings.get(account__type="person").person == ramesh
    assert services.person_net(ramesh) == services.PersonNet(D("5000.00"), D("0.00"))

    part = services.settle(
        workspace,
        person=ramesh,
        amount=D("2000.00"),
        direction=services.RECEIVED,
        account=sbi,
        date=NOV_5,
    )

    assert postings(part) == {"SBI": D("2000.00"), "Ramesh": D("-2000.00")}
    assert part.kind == "settle"
    assert services.person_net(ramesh).owes_me == D("3000.00")

    services.settle(
        workspace, person=ramesh, amount=D("3000.00"), direction=services.RECEIVED, account=sbi
    )

    assert services.person_net(ramesh) == services.PersonNet(D("0.00"), D("0.00"))
    assert services.account_balance(sbi) == D("50000.00")
    assert expense_total(workspace) == D("0.00")


def test_borrow_then_repay(workspace, sbi, ramesh):
    borrowed = services.borrow(workspace, person=ramesh, amount=D("8000.00"), account=sbi)

    assert postings(borrowed) == {"SBI": D("8000.00"), "Ramesh": D("-8000.00")}
    assert borrowed.kind == "borrow"
    assert services.person_net(ramesh) == services.PersonNet(D("0.00"), D("8000.00"))

    repaid = services.settle(
        workspace, person=ramesh, amount=D("8000.00"), direction=services.PAID, account=sbi
    )

    assert postings(repaid) == {"SBI": D("-8000.00"), "Ramesh": D("8000.00")}
    assert services.person_net(ramesh).i_owe == D("0.00")
    assert services.account_balance(sbi) == D("50000.00")


def test_settle_needs_a_direction(workspace, sbi, ramesh):
    with pytest.raises(ValidationError, match="Direction"):
        services.settle(workspace, person=ramesh, amount=D("1.00"), direction="in", account=sbi)


def test_a_persons_ledger_is_created_once_and_reused(workspace, sbi, ramesh):
    services.lend(workspace, person=ramesh, amount=D("100.00"), account=sbi)
    services.lend(workspace, person=ramesh, amount=D("200.00"), account=sbi)

    ledger = Account.objects.get(type="person")
    assert (ledger.name, ledger.person) == ("Ramesh", ramesh)
    assert services.account_balance(ledger) == D("300.00")


def test_lending_through_a_payment_app(workspace, phonepe, sbi, ramesh):
    txn = services.lend(workspace, person=ramesh, amount=D("5000.00"), payment_app=phonepe)

    assert postings(txn)["SBI"] == D("-5000.00")
    assert txn.payment_app == phonepe


def test_entries_can_target_one_of_a_persons_ledgers(workspace, sbi):
    brajesh = person(workspace, "Brajesh")
    personal = account(workspace, "Brajesh (Personal)", "person", person=brajesh)
    deals = account(workspace, "Brajesh (Vishnu Wings)", "person", person=brajesh)

    services.lend(workspace, person=brajesh, amount=D("5000.00"), account=sbi, ledger=personal)
    services.borrow(workspace, person=brajesh, amount=D("2000.00"), account=sbi, ledger=deals)

    net = services.person_net(brajesh)
    assert (net.owes_me, net.i_owe, net.net) == (D("5000.00"), D("2000.00"), D("3000.00"))


def test_a_ledger_must_belong_to_the_person(workspace, sbi, ramesh):
    father = person(workspace, "Father")
    fathers = account(workspace, "Father", "person", person=father)

    with pytest.raises(ValidationError, match="not a ledger of Ramesh"):
        services.lend(workspace, person=ramesh, amount=D("1.00"), account=sbi, ledger=fathers)


# --- pay_from_proxy: Father ₹10,000 to Ramesh ---


@pytest.fixture
def father(workspace):
    return person(workspace, "Father")


@pytest.fixture
def fathers_sbi(workspace, father):
    return account(workspace, "Father's SBI", "proxy", person=father, track_balance=False)


def test_paying_ramesh_10000_from_fathers_account(
    workspace, sbi, cash, ramesh, father, fathers_sbi
):
    txn = services.pay_from_proxy(
        workspace, proxy_account=fathers_sbi, recipient=ramesh, amount=D("10000.00")
    )

    assert postings(txn) == {"Ramesh": D("10000.00"), "Father": D("-10000.00")}
    assert services.person_net(ramesh) == services.PersonNet(D("10000.00"), D("0.00"))
    assert services.person_net(father) == services.PersonNet(D("0.00"), D("10000.00"))
    # The proxy is on the transaction for traceability, and nothing else moved.
    assert txn.proxy_account == fathers_sbi
    assert fathers_sbi.postings.count() == 0
    assert services.account_balance(fathers_sbi) == D("0.00")
    assert services.account_balance(sbi) == D("50000.00")
    assert services.account_balance(cash) == D("0.00")
    assert not txn.postings.filter(account__track_balance=False).exists()
    # Father's money stays traceable on what Ramesh owes.
    assert txn.postings.get(person=ramesh).funding_owner == father
    assert expense_total(workspace) == D("0.00")


def test_ramesh_repays_me_and_i_repay_father(workspace, sbi, ramesh, father, fathers_sbi):
    services.pay_from_proxy(
        workspace, proxy_account=fathers_sbi, recipient=ramesh, amount=D("10000.00")
    )

    services.settle(
        workspace, person=ramesh, amount=D("10000.00"), direction=services.RECEIVED, account=sbi
    )
    services.settle(
        workspace, person=father, amount=D("10000.00"), direction=services.PAID, account=sbi
    )

    assert services.person_net(ramesh).net == D("0.00")
    assert services.person_net(father).net == D("0.00")
    assert services.account_balance(sbi) == D("50000.00")


def test_pay_from_proxy_needs_a_proxy_account_and_another_person(
    workspace, sbi, ramesh, father, fathers_sbi
):
    with pytest.raises(ValidationError, match="not a proxy account"):
        services.pay_from_proxy(workspace, proxy_account=sbi, recipient=ramesh, amount=D("1.00"))
    with pytest.raises(ValidationError, match="owns this account"):
        services.pay_from_proxy(
            workspace, proxy_account=fathers_sbi, recipient=father, amount=D("1.00")
        )


@pytest.mark.parametrize("entry", ["spend", "lend", "transfer"])
def test_a_proxy_account_can_never_be_posted_to(workspace, sbi, ramesh, fathers_sbi, entry):
    calls = {
        "spend": lambda: services.spend(workspace, amount=D("1.00"), account=fathers_sbi),
        "lend": lambda: services.lend(
            workspace, person=ramesh, amount=D("1.00"), account=fathers_sbi
        ),
        "transfer": lambda: services.transfer(
            workspace, amount=D("1.00"), from_account=sbi, to_account=fathers_sbi
        ),
    }

    with pytest.raises(ValidationError, match="pay_from_proxy"):
        calls[entry]()
    assert not Posting.objects.exists()


# --- pay_on_behalf: ₹3,000 to Person C for Friend ---


def test_paying_person_c_3000_on_behalf_of_friend(workspace, sbi):
    friend = person(workspace, "Friend")
    person_c = person(workspace, "Person C")
    services.borrow(workspace, person=friend, amount=D("5000.00"), account=sbi)

    txn = services.pay_on_behalf(
        workspace, on_behalf_of=friend, payee=person_c, amount=D("3000.00"), account=sbi
    )

    assert postings(txn) == {"Friend": D("3000.00"), "SBI": D("-3000.00")}
    assert txn.on_behalf_of == friend
    assert txn.description == "Paid Person C on behalf of Friend"
    # My debt to Friend falls from 5,000 to 2,000.
    assert services.person_net(friend) == services.PersonNet(D("0.00"), D("2000.00"))
    # Person C owes nothing and has no ledger at all.
    assert services.person_net(person_c) == services.PersonNet(D("0.00"), D("0.00"))
    assert not person_c.accounts.exists()
    assert not Posting.objects.filter(person=person_c).exists()
    assert services.account_balance(sbi) == D("52000.00")
    assert expense_total(workspace) == D("0.00")


def test_pay_on_behalf_takes_a_plain_payee_name_and_a_payment_app(workspace, phonepe):
    friend = person(workspace, "Friend")

    txn = services.pay_on_behalf(
        workspace, on_behalf_of=friend, payee="Hotel", amount=D("3000.00"), payment_app=phonepe
    )

    assert txn.description == "Paid Hotel on behalf of Friend"
    assert postings(txn)["SBI"] == D("-3000.00")
    # With no earlier debt, Friend now owes me.
    assert services.person_net(friend).owes_me == D("3000.00")


# --- Balance helpers ---


def test_account_balance_as_of_a_date(workspace, sbi, food):
    services.spend(workspace, amount=D("100.00"), account=sbi, category=food, date=NOV_1)
    services.spend(workspace, amount=D("250.00"), account=sbi, category=food, date=NOV_5)

    assert services.account_balance(sbi, datetime.date(2026, 10, 31)) == D("50000.00")
    assert services.account_balance(sbi, NOV_1) == D("49900.00")
    assert services.account_balance(sbi, NOV_5) == D("49650.00")
    assert services.account_balance(sbi) == D("49650.00")
    assert isinstance(services.account_balance(sbi), Decimal)


def test_account_balance_of_an_untouched_account_is_its_opening_balance(sbi, cash):
    assert services.account_balance(sbi) == D("50000.00")
    assert services.account_balance(cash) == D("0.00")


def test_person_net_includes_opening_dues_and_respects_as_of(workspace, sbi, ramesh):
    account(workspace, "Ramesh", "person", person=ramesh, opening_balance=D("-1500.00"))

    assert services.person_net(ramesh) == services.PersonNet(D("0.00"), D("1500.00"))

    services.lend(workspace, person=ramesh, amount=D("4000.00"), account=sbi, date=NOV_5)

    assert services.person_net(ramesh, NOV_1).i_owe == D("1500.00")
    assert services.person_net(ramesh, NOV_5) == services.PersonNet(D("2500.00"), D("0.00"))


def test_person_net_ignores_a_persons_proxy_account(father, fathers_sbi):
    assert services.person_net(father) == services.PersonNet(D("0.00"), D("0.00"))


# --- Rules shared by every entry ---


@pytest.mark.parametrize("amount", [450.0, 450.5, True, None])
def test_amounts_that_are_not_decimal_are_a_type_error(workspace, sbi, food, amount):
    with pytest.raises(TypeError, match="must be Decimal"):
        services.spend(workspace, amount=amount, account=sbi, category=food)


@pytest.mark.parametrize(
    ("amount", "message"),
    [
        (D("0.00"), "more than zero"),
        (D("-5.00"), "more than zero"),
        (D("10.005"), "2 decimal places"),
        ("abc", "not an amount"),
        (D("NaN"), "more than zero"),
    ],
)
def test_bad_amounts_are_refused(workspace, sbi, food, amount, message):
    with pytest.raises(ValidationError, match=message):
        services.spend(workspace, amount=amount, account=sbi, category=food)
    assert not Transaction.objects.exists()


def test_whole_and_string_amounts_are_stored_with_two_places(workspace, sbi, food):
    whole = services.spend(workspace, amount=450, account=sbi, category=food)
    text = services.spend(workspace, amount="120.5", account=sbi, category=food)

    assert str(whole.postings.get(account=sbi).amount) == "-450.00"
    assert str(text.postings.get(account=sbi).amount) == "-120.50"


def test_every_entry_type_is_saved_balanced(workspace, sbi, cash, food, salary, ramesh):
    father = person(workspace, "Father")
    proxy = account(workspace, "Father's SBI", "proxy", person=father, track_balance=False)
    amount = D("33.33")

    saved = [
        services.spend(workspace, amount=amount, account=sbi, category=food),
        services.spend_with_items(workspace, account=sbi, items=[Item("Tea", amount, food)]),
        services.receive(workspace, amount=amount, account=sbi, category=salary),
        services.transfer(workspace, amount=amount, from_account=sbi, to_account=cash),
        services.lend(workspace, person=ramesh, amount=amount, account=sbi),
        services.borrow(workspace, person=ramesh, amount=amount, account=sbi),
        services.settle(
            workspace, person=ramesh, amount=amount, direction=services.PAID, account=sbi
        ),
        services.pay_from_proxy(workspace, proxy_account=proxy, recipient=ramesh, amount=amount),
        services.pay_on_behalf(
            workspace, on_behalf_of=ramesh, payee="Shop", amount=amount, account=sbi
        ),
    ]

    for txn in saved:
        assert isinstance(txn, Transaction)
        assert txn.postings.count() >= 2
        assert txn.postings.aggregate(total=Sum("amount"))["total"] == 0
        assert {p.workspace for p in txn.postings.all()} == {workspace}


def test_every_entry_is_written_to_the_audit_log(workspace, sbi, food, user):
    txn = services.spend(workspace, amount=D("450.00"), account=sbi, category=food, created_by=user)

    entry = AuditLog.objects.get()
    assert (entry.target, entry.action, entry.actor) == (txn, "create", user)
    assert entry.workspace == workspace


def test_a_retried_entry_with_the_same_client_uuid_is_saved_once(workspace, sbi, food):
    client_uuid = uuid.uuid4()
    kwargs = {"amount": D("450.00"), "account": sbi, "category": food, "client_uuid": client_uuid}

    first = services.spend(workspace, **kwargs)
    second = services.spend(workspace, **kwargs)

    assert first == second
    assert first.client_uuid == client_uuid
    assert Transaction.objects.count() == 1
    assert services.account_balance(sbi) == D("49550.00")


def test_a_failed_entry_saves_nothing(workspace, sbi, food, other_workspace):
    their_tag = Tag.objects.create(workspace=other_workspace, name="bike")

    with pytest.raises(ValidationError):
        services.spend(workspace, amount=D("450.00"), account=sbi, category=food, tags=[their_tag])

    assert not Transaction.objects.exists()
    assert not Posting.objects.exists()
    assert not AuditLog.objects.exists()


def test_a_closed_account_cannot_be_used(workspace, sbi, food):
    sbi.is_active = False
    sbi.save()

    with pytest.raises(ValidationError, match="closed"):
        services.spend(workspace, amount=D("1.00"), account=sbi, category=food)


# --- Workspace isolation ---


def test_nothing_from_another_workspace_can_be_used(workspace, other_workspace, sbi, food, ramesh):
    their_bank = account(other_workspace, "SBI")
    their_food = category(other_workspace, "Food")
    their_person = person(other_workspace, "Ramesh")
    their_app = PaymentApp.objects.create(
        workspace=other_workspace, name="PhonePe", default_account=their_bank
    )
    their_book = Book.objects.create(workspace=other_workspace, name="Personal")
    their_proxy = account(
        other_workspace, "Proxy", "proxy", person=their_person, track_balance=False
    )
    one = D("1.00")
    calls = [
        lambda: services.spend(workspace, amount=one, account=their_bank, category=food),
        lambda: services.spend(workspace, amount=one, account=sbi, category=their_food),
        lambda: services.spend(workspace, amount=one, payment_app=their_app, category=food),
        lambda: services.spend(workspace, amount=one, account=sbi, category=food, book=their_book),
        lambda: services.spend_with_items(
            workspace, account=sbi, items=[Item("Tea", one, their_food)]
        ),
        lambda: services.receive(workspace, amount=one, account=their_bank),
        lambda: services.transfer(workspace, amount=one, from_account=sbi, to_account=their_bank),
        lambda: services.lend(workspace, person=their_person, amount=one, account=sbi),
        lambda: services.borrow(workspace, person=their_person, amount=one, account=sbi),
        lambda: services.settle(
            workspace, person=their_person, amount=one, direction=services.PAID, account=sbi
        ),
        lambda: services.pay_from_proxy(
            workspace, proxy_account=their_proxy, recipient=ramesh, amount=one
        ),
        lambda: services.pay_on_behalf(
            workspace, on_behalf_of=their_person, payee="Shop", amount=one, account=sbi
        ),
    ]

    for call in calls:
        with pytest.raises(ValidationError, match="different workspace"):
            call()
    assert not Transaction.objects.exists()
    assert not Account.objects.filter(workspace=workspace, type="person").exists()


def test_balances_never_include_another_workspaces_entries(workspace, other_workspace, sbi, food):
    their_bank = account(other_workspace, "SBI", opening_balance=D("100.00"))
    services.spend(other_workspace, amount=D("40.00"), account=their_bank)

    assert services.account_balance(sbi) == D("50000.00")
    assert services.account_balance(their_bank) == D("60.00")
    assert expense_total(workspace) == D("0.00")
