from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from core.models import WorkspaceModel


class Category(WorkspaceModel):
    """Where spending goes or income comes from. Two levels: category and sub-category."""

    class Kind(models.TextChoices):
        EXPENSE = "expense", "Expense"
        INCOME = "income", "Income"

    name = models.CharField(max_length=100)
    parent = models.ForeignKey(
        "self", on_delete=models.RESTRICT, null=True, blank=True, related_name="children"
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)

    class Meta:
        ordering = ["kind", "name"]
        verbose_name_plural = "categories"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "kind", "name"],
                condition=Q(parent__isnull=True),
                name="category_unique_top_level_name",
            ),
            models.UniqueConstraint(
                fields=["workspace", "parent", "name"],
                condition=Q(parent__isnull=False),
                name="category_unique_name_in_parent",
            ),
        ]

    def __str__(self):
        return f"{self.parent.name} › {self.name}" if self.parent_id else self.name

    def clean(self):
        super().clean()
        if self.parent_id is None:
            return
        if self.parent_id == self.pk:
            raise ValidationError({"parent": "A category cannot be its own parent."})
        if self.parent.parent_id is not None:
            raise ValidationError({"parent": "Categories go only two levels deep."})
        if self.parent.kind != self.kind:
            raise ValidationError({"kind": "A sub-category has the same kind as its parent."})
        if self.pk and self.children.exists():
            raise ValidationError({"parent": "A category with sub-categories cannot be nested."})


class Tag(WorkspaceModel):
    """A free label across categories: #bike, #kartik-yatra, #brother."""

    name = models.CharField(max_length=50)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["workspace", "name"], name="tag_unique_name"),
        ]

    def __str__(self):
        return self.name


class Merchant(WorkspaceModel):
    """A payee that remembers its usual category, payment app and account."""

    name = models.CharField(max_length=100)
    default_category = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    default_payment_app = models.ForeignKey(
        "ledger.PaymentApp", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    default_account = models.ForeignKey(
        "ledger.Account", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["workspace", "name"], name="merchant_unique_name"),
        ]

    def __str__(self):
        return self.name
