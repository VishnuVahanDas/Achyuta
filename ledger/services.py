"""Business logic for the ledger app. Views call these; they never write models directly.

Every entry function is atomic, takes the workspace first, and returns the saved
Transaction. Each builds postings whose signed amounts sum to zero (positive means
the account goes up). The optional keyword details shared by all of them are listed
in DETAILS.
"""

from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from catalog.models import Category

from .models import Account, AuditLog, LineItem, Posting, Transaction

ZERO = Decimal("0.00")
CENT = Decimal("0.01")

# Accounts you can pay from or receive into, and those a transfer can move between.
MONEY_TYPES = {Account.Type.BANK, Account.Type.CASH, Account.Type.CARD, Account.Type.WALLET}
TRANSFER_TYPES = MONEY_TYPES | {Account.Type.FD}

# settle() directions.
RECEIVED = "received"  # the person paid me back
PAID = "paid"  # I paid the person back

# Optional keyword arguments accepted by every entry function.
DETAILS = {
    "description",
    "merchant",
    "mode",
    "utr",
    "book",
    "tags",
    "status",
    "client_uuid",
    "created_by",
}


@dataclass(frozen=True)
class Item:
    """One line of a detailed purchase, as passed to spend_with_items()."""

    name: str
    amount: Decimal
    category: object = None
    qty: Decimal = Decimal("1")


@dataclass(frozen=True)
class PersonNet:
    """What a person owes me and what I owe them, each summed over their ledgers."""

    owes_me: Decimal
    i_owe: Decimal

    @property
    def net(self):
        """Positive when the person owes me overall, negative when I owe them."""
        return self.owes_me - self.i_owe


@dataclass(frozen=True)
class _Line:
    account: Account
    amount: Decimal
    category: object = None
    person: object = None
    funding_owner: object = None


# --- Entry functions ---


@transaction.atomic
def spend(
    workspace, *, amount, account=None, payment_app=None, category=None, date=None, **details
):
    """Pay for something. Without a category it is saved as a draft for To review."""
    amount = _money(amount)
    _require_kind(category, Category.Kind.EXPENSE)
    account = _resolve_account(workspace, account, payment_app)
    lines = [
        _Line(account, -amount),
        _Line(_system_account(workspace, Account.Type.EXPENSE), amount, category=category),
    ]
    return _post(
        workspace,
        Transaction.Kind.SPEND,
        lines,
        date=date,
        payment_app=payment_app,
        complete=category is not None,
        details=details,
    )


@transaction.atomic
def spend_with_items(
    workspace, *, items, amount=None, account=None, payment_app=None, date=None, **details
):
    """A purchase split into items: one debit on the account, one expense per category.

    `amount`, when given, is the bill total and must equal the sum of the items.
    """
    items = [_clean_item(item) for item in items]
    if not items:
        raise ValidationError("Add at least one item.")
    total = sum(item.amount for item in items)
    if amount is not None and _money(amount) != total:
        raise ValidationError(f"Items add up to {total}, not {_money(amount)}.")
    account = _resolve_account(workspace, account, payment_app)

    by_category = {}
    for item in items:
        by_category[item.category] = by_category.get(item.category, ZERO) + item.amount
    expenses = _system_account(workspace, Account.Type.EXPENSE)
    lines = [_Line(account, -total)]
    lines += [_Line(expenses, subtotal, category=cat) for cat, subtotal in by_category.items()]
    return _post(
        workspace,
        Transaction.Kind.SPEND,
        lines,
        date=date,
        payment_app=payment_app,
        complete=None not in by_category,
        items=items,
        details=details,
    )


@transaction.atomic
def receive(
    workspace, *, amount, account=None, payment_app=None, category=None, date=None, **details
):
    """Income arrives. Without a category it is saved as a draft for To review."""
    amount = _money(amount)
    _require_kind(category, Category.Kind.INCOME)
    account = _resolve_account(workspace, account, payment_app)
    lines = [
        _Line(account, amount),
        _Line(_system_account(workspace, Account.Type.INCOME), -amount, category=category),
    ]
    return _post(
        workspace,
        Transaction.Kind.RECEIVE,
        lines,
        date=date,
        payment_app=payment_app,
        complete=category is not None,
        details=details,
    )


@transaction.atomic
def transfer(
    workspace, *, amount, to_account, from_account=None, payment_app=None, date=None, **details
):
    """Move money between your own accounts (ATM, FD, card bill). Never an expense."""
    amount = _money(amount)
    from_account = _resolve_account(workspace, from_account, payment_app, allowed=TRANSFER_TYPES)
    _require_type(to_account, TRANSFER_TYPES)
    if to_account == from_account:
        raise ValidationError("Choose two different accounts.")
    lines = [_Line(from_account, -amount), _Line(to_account, amount)]
    return _post(
        workspace,
        Transaction.Kind.TRANSFER,
        lines,
        date=date,
        payment_app=payment_app,
        details=details,
    )


@transaction.atomic
def lend(
    workspace,
    *,
    person,
    amount,
    account=None,
    payment_app=None,
    ledger=None,
    date=None,
    **details,
):
    """Give money to a person, who then owes it back."""
    amount = _money(amount)
    account = _resolve_account(workspace, account, payment_app)
    ledger = _person_ledger(workspace, person, ledger)
    lines = [_Line(account, -amount), _Line(ledger, amount, person=person)]
    return _post(
        workspace,
        Transaction.Kind.LEND,
        lines,
        date=date,
        payment_app=payment_app,
        details=details,
    )


@transaction.atomic
def borrow(
    workspace,
    *,
    person,
    amount,
    account=None,
    payment_app=None,
    ledger=None,
    date=None,
    **details,
):
    """Take money from a person, whom I then owe."""
    amount = _money(amount)
    account = _resolve_account(workspace, account, payment_app)
    ledger = _person_ledger(workspace, person, ledger)
    lines = [_Line(account, amount), _Line(ledger, -amount, person=person)]
    return _post(
        workspace,
        Transaction.Kind.BORROW,
        lines,
        date=date,
        payment_app=payment_app,
        details=details,
    )


@transaction.atomic
def settle(
    workspace,
    *,
    person,
    amount,
    direction,
    account=None,
    payment_app=None,
    ledger=None,
    date=None,
    **details,
):
    """Repayment, in full or in part. RECEIVED: the person paid me. PAID: I paid them."""
    if direction not in (RECEIVED, PAID):
        raise ValidationError("Direction must be 'received' or 'paid'.")
    amount = _money(amount)
    account = _resolve_account(workspace, account, payment_app)
    ledger = _person_ledger(workspace, person, ledger)
    into_account = amount if direction == RECEIVED else -amount
    lines = [_Line(account, into_account), _Line(ledger, -into_account, person=person)]
    return _post(
        workspace,
        Transaction.Kind.SETTLE,
        lines,
        date=date,
        payment_app=payment_app,
        details=details,
    )


@transaction.atomic
def pay_from_proxy(workspace, *, proxy_account, recipient, amount, date=None, **details):
    """Pay a person from someone else's account (e.g. Father's SBI).

    The recipient owes me and I owe the proxy's owner. The proxy account is recorded
    on the transaction but gets no posting, so no tracked balance changes.
    """
    amount = _money(amount)
    if proxy_account.type != Account.Type.PROXY:
        raise ValidationError(f"{proxy_account} is not a proxy account.")
    owner = proxy_account.person
    if recipient == owner:
        raise ValidationError(f"{owner} owns this account; this is not a loan to them.")
    lines = [
        _Line(_person_ledger(workspace, recipient), amount, person=recipient, funding_owner=owner),
        _Line(_person_ledger(workspace, owner), -amount, person=owner),
    ]
    return _post(
        workspace,
        Transaction.Kind.LEND,
        lines,
        date=date,
        proxy_account=proxy_account,
        details=details,
    )


@transaction.atomic
def pay_on_behalf(
    workspace,
    *,
    on_behalf_of,
    payee,
    amount,
    account=None,
    payment_app=None,
    ledger=None,
    date=None,
    **details,
):
    """Pay a third party to settle someone else's obligation.

    My debt to `on_behalf_of` falls (or they owe me more). The payee, a name or a
    Person, owes nothing and gets no posting.
    """
    amount = _money(amount)
    account = _resolve_account(workspace, account, payment_app)
    ledger = _person_ledger(workspace, on_behalf_of, ledger)
    details.setdefault("description", f"Paid {payee} on behalf of {on_behalf_of}")
    lines = [_Line(account, -amount), _Line(ledger, amount, person=on_behalf_of)]
    return _post(
        workspace,
        Transaction.Kind.SETTLE,
        lines,
        date=date,
        payment_app=payment_app,
        on_behalf_of=on_behalf_of,
        details=details,
    )


# --- Balance helpers ---


def account_balance(account, as_of=None, *, include_drafts=True):
    """Opening balance plus every posting dated up to `as_of` (default: all).

    Untracked (proxy) accounts always report zero. Drafts count unless excluded:
    a quick entry still waiting in To review has already moved the money.
    """
    if not account.track_balance:
        return ZERO
    postings = _dated(account.postings.all(), as_of, include_drafts)
    return account.opening_balance + (postings.aggregate(total=Sum("amount"))["total"] or ZERO)


def person_net(person, as_of=None, *, include_drafts=True):
    """Split a person's position into owes_me and i_owe across all their ledgers.

    A ledger with a positive balance adds to owes_me, a negative one to i_owe, so
    someone with two ledgers (e.g. personal and deals) can appear on both sides.
    """
    ledgers = Account.objects.filter(
        workspace=person.workspace, person=person, type=Account.Type.PERSON
    )
    postings = _dated(Posting.objects.filter(account__in=ledgers), as_of, include_drafts)
    posted = dict(postings.values_list("account").annotate(total=Sum("amount")))
    owes_me = i_owe = ZERO
    for ledger in ledgers:
        balance = ledger.opening_balance + posted.get(ledger.pk, ZERO)
        if balance > 0:
            owes_me += balance
        else:
            i_owe -= balance
    return PersonNet(owes_me=owes_me, i_owe=i_owe)


# --- Internals ---


def _dated(postings, as_of, include_drafts):
    if as_of is not None:
        postings = postings.filter(transaction__date__lte=as_of)
    if not include_drafts:
        postings = postings.filter(transaction__status=Transaction.Status.CONFIRMED)
    return postings


def _money(amount):
    """Return a positive Decimal with at most 2 places. Floats are refused, never rounded."""
    if isinstance(amount, float | bool) or not isinstance(amount, Decimal | int | str):
        raise TypeError(f"Amounts must be Decimal, not {type(amount).__name__}.")
    try:
        amount = Decimal(amount)
    except ArithmeticError as error:
        raise ValidationError(f"{amount!r} is not an amount.") from error
    if not amount.is_finite() or amount <= 0:
        raise ValidationError("Amount must be more than zero.")
    if amount != amount.quantize(CENT):
        raise ValidationError("Amount cannot have more than 2 decimal places.")
    return amount.quantize(CENT)


def _clean_item(item):
    if not str(item.name).strip():
        raise ValidationError("Every item needs a name.")
    qty = item.qty
    if isinstance(qty, bool) or not isinstance(qty, Decimal | int) or qty <= 0:
        raise ValidationError(f"Quantity for {item.name} must be a number more than zero.")
    _require_kind(item.category, Category.Kind.EXPENSE)
    return Item(item.name, _money(item.amount), item.category, Decimal(qty))


def _require_kind(category, kind):
    if category is not None and category.kind != kind:
        raise ValidationError(f"{category} is not an {kind} category.")


def _require_type(account, allowed):
    if account.type == Account.Type.PROXY:
        raise ValidationError(
            f"{account} is someone else's account; use pay_from_proxy() to pay from it."
        )
    if account.type not in allowed or not account.track_balance:
        raise ValidationError(f"{account} cannot be used for this entry.")
    if not account.is_active:
        raise ValidationError(f"{account} is closed.")


def _resolve_account(workspace, account, payment_app, allowed=MONEY_TYPES):
    """The account money moves through: the one passed, else the app's default bank."""
    if account is None:
        if payment_app is None:
            raise ValidationError("Choose an account or a payment app.")
        account = payment_app.default_account
    elif payment_app is not None:
        linked = account == payment_app.default_account or (
            payment_app.other_accounts.filter(pk=account.pk).exists()
        )
        if not linked:
            raise ValidationError(f"{payment_app} is not linked to {account}.")
    _require_type(account, allowed)
    return account


def _system_account(workspace, type):
    """The workspace's single Expenses or Income account, created on first use."""
    account = Account.objects.filter(workspace=workspace, type=type).order_by("pk").first()
    if account is None:
        name = {Account.Type.EXPENSE: "Expenses", Account.Type.INCOME: "Income"}[type]
        account = Account.objects.create(workspace=workspace, type=type, name=name)
    return account


def _person_ledger(workspace, person, ledger=None):
    """The ledger to post a person's dues to: the one passed, else their first, else a new one."""
    if ledger is not None:
        if ledger.type != Account.Type.PERSON or ledger.person_id != person.pk:
            raise ValidationError(f"{ledger} is not a ledger of {person}.")
        return ledger
    _same_workspace(workspace, person)
    ledgers = Account.objects.filter(workspace=workspace, person=person, type=Account.Type.PERSON)
    ledger = ledgers.order_by("pk").first()
    if ledger is None:
        name = person.name
        if Account.objects.filter(workspace=workspace, name=name).exists():
            name = f"{name} (ledger)"
        ledger = Account.objects.create(
            workspace=workspace, type=Account.Type.PERSON, person=person, name=name
        )
    return ledger


def _same_workspace(workspace, *objects):
    """Refuse anything that belongs to another workspace."""
    for obj in objects:
        if obj is not None and obj.workspace_id != workspace.pk:
            raise ValidationError(f"{obj} belongs to a different workspace.")


def _post(
    workspace,
    kind,
    lines,
    *,
    details,
    date=None,
    payment_app=None,
    on_behalf_of=None,
    proxy_account=None,
    complete=True,
    items=(),
):
    """Validate and save one transaction with its postings, items and audit entry."""
    unknown = details.keys() - DETAILS
    if unknown:
        raise TypeError(f"Unexpected arguments: {', '.join(sorted(unknown))}.")

    # A retried entry (same client_uuid) returns the one already saved.
    client_uuid = details.get("client_uuid")
    if client_uuid is not None:
        existing = Transaction.objects.filter(workspace=workspace, client_uuid=client_uuid)
        if existing.exists():
            return existing.get()

    tags = list(details.get("tags") or [])
    _same_workspace(
        workspace,
        payment_app,
        on_behalf_of,
        proxy_account,
        details.get("merchant"),
        details.get("book"),
        *tags,
        *(item.category for item in items),
        *(obj for ln in lines for obj in (ln.account, ln.category, ln.person, ln.funding_owner)),
    )
    if len(lines) < 2 or sum(line.amount for line in lines) != 0:
        raise ValidationError("Postings must be two or more and sum to zero.")

    default_status = Transaction.Status.CONFIRMED if complete else Transaction.Status.DRAFT
    txn = Transaction(
        workspace=workspace,
        kind=kind,
        date=date or timezone.localdate(),
        description=details.get("description", ""),
        merchant=details.get("merchant"),
        payment_app=payment_app,
        mode=details.get("mode") or (Transaction.Mode.UPI if payment_app else ""),
        utr=details.get("utr", ""),
        book=details.get("book"),
        on_behalf_of=on_behalf_of,
        proxy_account=proxy_account,
        status=details.get("status") or default_status,
        created_by=details.get("created_by"),
    )
    if client_uuid is not None:
        txn.client_uuid = client_uuid
    txn.save()
    txn.tags.set(tags)
    Posting.objects.bulk_create(
        Posting(
            workspace=workspace,
            transaction=txn,
            account=line.account,
            amount=line.amount,
            category=line.category,
            person=line.person,
            funding_owner=line.funding_owner,
        )
        for line in lines
    )
    LineItem.objects.bulk_create(
        LineItem(
            workspace=workspace,
            transaction=txn,
            name=item.name,
            amount=item.amount,
            category=item.category,
            qty=item.qty,
        )
        for item in items
    )
    AuditLog.objects.create(
        workspace=workspace,
        target=txn,
        action=AuditLog.Action.CREATE,
        actor=details.get("created_by"),
    )
    return txn
