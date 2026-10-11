import uuid
from pathlib import Path

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Q

from core.fields import MoneyField
from core.models import WorkspaceModel

from .storage import PrivateStorage


class Book(WorkspaceModel):
    """Whose business an entry belongs to: Personal, Vinatay, HolyTrail, Vishnu Wings."""

    class Kind(models.TextChoices):
        PERSONAL = "personal", "Personal"
        COMPANY = "company", "Company"
        INVESTMENT = "investment", "Investment"

    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.PERSONAL)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["workspace", "name"], name="book_unique_name"),
        ]

    def __str__(self):
        return self.name


class Person(WorkspaceModel):
    """Anyone you owe or who owes you. One person can have several ledgers (person accounts)."""

    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "people"
        constraints = [
            models.UniqueConstraint(fields=["workspace", "name"], name="person_unique_name"),
        ]

    def __str__(self):
        return self.name


class Account(WorkspaceModel):
    """A place money sits, or a party money is owed to or by."""

    class Type(models.TextChoices):
        BANK = "bank", "Bank"
        CASH = "cash", "Cash"
        CARD = "card", "Card"
        WALLET = "wallet", "Wallet"
        FD = "fd", "Fixed deposit"
        PROXY = "proxy", "Proxy"
        PERSON = "person", "Person"
        FUND = "fund", "Fund"
        CAPITAL = "capital", "Capital"
        INCOME = "income", "Income"
        EXPENSE = "expense", "Expense"

    name = models.CharField(max_length=100)
    type = models.CharField(max_length=20, choices=Type.choices)
    book = models.ForeignKey(
        Book, on_delete=models.RESTRICT, null=True, blank=True, related_name="accounts"
    )
    # The person a Person ledger is with, or the owner of a Proxy account.
    person = models.ForeignKey(
        Person, on_delete=models.RESTRICT, null=True, blank=True, related_name="accounts"
    )
    opening_balance = MoneyField(default=0)
    # False for Proxy accounts: someone else's money, so no balance is kept.
    track_balance = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["workspace", "name"], name="account_unique_name"),
            models.CheckConstraint(
                condition=~Q(type="proxy") | Q(track_balance=False),
                name="account_proxy_not_tracked",
                violation_error_message="A proxy account cannot track a balance.",
            ),
            models.CheckConstraint(
                condition=~Q(type__in=["proxy", "person"]) | Q(person__isnull=False),
                name="account_person_required",
                violation_error_message="Person and proxy accounts need a person.",
            ),
        ]

    def __str__(self):
        return self.name


class PaymentApp(WorkspaceModel):
    """How money moved (PhonePe, GPay). A tag on a bank account, never an account itself."""

    name = models.CharField(max_length=100)
    default_account = models.ForeignKey(
        Account, on_delete=models.RESTRICT, related_name="default_for_apps"
    )
    other_accounts = models.ManyToManyField(Account, blank=True, related_name="other_apps")

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["workspace", "name"], name="paymentapp_unique_name"),
        ]

    def __str__(self):
        return self.name


class Transaction(WorkspaceModel):
    """One user action. Holds two or more postings whose signed amounts sum to zero.

    The database refuses to commit a confirmed transaction that does not balance
    (constraint trigger ledger_transaction_postings_balanced).
    """

    class Kind(models.TextChoices):
        SPEND = "spend", "Spend"
        RECEIVE = "receive", "Receive"
        TRANSFER = "transfer", "Transfer"
        LEND = "lend", "Lend"
        BORROW = "borrow", "Borrow"
        SETTLE = "settle", "Settle"
        OPENING = "opening", "Opening balance"

    class Mode(models.TextChoices):
        UPI = "upi", "UPI"
        NEFT = "neft", "NEFT"
        IMPS = "imps", "IMPS"
        RTGS = "rtgs", "RTGS"
        NETBANKING = "netbanking", "NetBanking"
        CASH = "cash", "Cash"
        CARD = "card", "Card"
        CHEQUE = "cheque", "Cheque"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        CONFIRMED = "confirmed", "Confirmed"

    date = models.DateField()
    kind = models.CharField(max_length=20, choices=Kind.choices)
    description = models.CharField(max_length=255, blank=True)
    merchant = models.ForeignKey(
        "catalog.Merchant",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="transactions",
    )
    payment_app = models.ForeignKey(
        PaymentApp, on_delete=models.RESTRICT, null=True, blank=True, related_name="transactions"
    )
    mode = models.CharField(max_length=20, choices=Mode.choices, blank=True)
    utr = models.CharField("UTR", max_length=50, blank=True)
    book = models.ForeignKey(
        Book, on_delete=models.RESTRICT, null=True, blank=True, related_name="transactions"
    )
    # The payment settled this person's obligation, not the payee's.
    on_behalf_of = models.ForeignKey(
        Person,
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="on_behalf_transactions",
    )
    # Someone else's account the money actually left from. Kept for traceability
    # only: it gets no posting, so its balance is never touched.
    proxy_account = models.ForeignKey(
        Account,
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="proxy_transactions",
        limit_choices_to={"type": Account.Type.PROXY},
    )
    tags = models.ManyToManyField("catalog.Tag", blank=True, related_name="transactions")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    # Set by the client so an offline entry that is retried is never saved twice.
    client_uuid = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["workspace", "date"])]

    def __str__(self):
        return f"{self.date} {self.get_kind_display()} {self.description}".strip()


class Posting(WorkspaceModel):
    """One side of a transaction: a signed amount on one account.

    Positive means the account goes up: money into a bank, a person owing you more,
    an expense. Negative is the reverse: money out of a bank, you owing a person,
    income, money held for a fund.
    """

    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, related_name="postings")
    account = models.ForeignKey(Account, on_delete=models.RESTRICT, related_name="postings")
    amount = MoneyField()
    category = models.ForeignKey(
        "catalog.Category",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="postings",
    )
    person = models.ForeignKey(
        Person, on_delete=models.RESTRICT, null=True, blank=True, related_name="postings"
    )
    # Whose money this is when it is borrowed (e.g. Father's). Empty means your own.
    funding_owner = models.ForeignKey(
        Person, on_delete=models.RESTRICT, null=True, blank=True, related_name="funded_postings"
    )

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=~Q(amount=0),
                name="posting_amount_not_zero",
                violation_error_message="A posting amount cannot be zero.",
            ),
        ]

    def __str__(self):
        return f"{self.account} {self.amount:+}"


class LineItem(WorkspaceModel):
    """One item inside a purchase, so a single bank debit can span categories."""

    transaction = models.ForeignKey(
        Transaction, on_delete=models.CASCADE, related_name="line_items"
    )
    name = models.CharField(max_length=200)
    amount = MoneyField()
    category = models.ForeignKey(
        "catalog.Category",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="line_items",
    )
    qty = models.DecimalField(max_digits=10, decimal_places=3, default=1)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.name} {self.amount}"


def attachment_path(instance, filename):
    """Store under the workspace with a random name, so paths reveal nothing."""
    suffix = Path(filename).suffix.lower()
    return f"workspace_{instance.workspace_id}/attachments/{uuid.uuid4().hex}{suffix}"


class Attachment(WorkspaceModel):
    """A receipt, screenshot or other proof, stored privately on the server."""

    class Kind(models.TextChoices):
        RECEIPT = "receipt", "Receipt"
        SCREENSHOT = "screenshot", "Screenshot"
        EIGHTY_G = "80g", "80G receipt"
        AGREEMENT = "agreement", "Agreement"

    transaction = models.ForeignKey(
        Transaction, on_delete=models.CASCADE, related_name="attachments"
    )
    file = models.FileField(upload_to=attachment_path, storage=PrivateStorage())
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.RECEIPT)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.get_kind_display()} for {self.transaction}"


class AuditLog(WorkspaceModel):
    """One recorded change to one field of one object. created_at is when it happened."""

    class Action(models.TextChoices):
        CREATE = "create", "Create"
        UPDATE = "update", "Update"
        DELETE = "delete", "Delete"

    content_type = models.ForeignKey(ContentType, on_delete=models.RESTRICT, related_name="+")
    object_id = models.PositiveBigIntegerField()
    target = GenericForeignKey("content_type", "object_id")
    action = models.CharField(max_length=10, choices=Action.choices)
    field = models.CharField(max_length=100, blank=True)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self):
        target = f"{self.content_type} #{self.object_id}"
        return f"{self.get_action_display()} {target} {self.field}".strip()
