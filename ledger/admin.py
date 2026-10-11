from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import models
from django.forms.models import BaseInlineFormSet

from core.admin import WorkspaceScopedAdmin, WorkspaceScopedInline

from .models import (
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


@admin.register(Book)
class BookAdmin(WorkspaceScopedAdmin):
    list_display = ("name", "kind", "workspace")
    list_filter = ("kind",)
    search_fields = ("name",)


@admin.register(Person)
class PersonAdmin(WorkspaceScopedAdmin):
    list_display = ("name", "phone", "workspace")
    search_fields = ("name", "phone")


@admin.register(Account)
class AccountAdmin(WorkspaceScopedAdmin):
    list_display = (
        "name",
        "type",
        "book",
        "person",
        "opening_balance",
        "track_balance",
        "is_active",
    )
    list_filter = ("type", "is_active", "track_balance")
    search_fields = ("name",)


@admin.register(PaymentApp)
class PaymentAppAdmin(WorkspaceScopedAdmin):
    list_display = ("name", "default_account", "workspace")
    search_fields = ("name",)
    filter_horizontal = ("other_accounts",)


class PostingFormSet(BaseInlineFormSet):
    """Report an unbalanced confirmed transaction as a form error before the database refuses it."""

    def clean(self):
        super().clean()
        if self.instance.status != Transaction.Status.CONFIRMED or any(self.errors):
            return
        amounts = [
            form.cleaned_data["amount"]
            for form in self.forms
            if form.cleaned_data and not form.cleaned_data.get("DELETE")
        ]
        if len(amounts) < 2 or sum(amounts) != 0:
            raise ValidationError(
                "A confirmed transaction needs two or more postings that sum to zero."
            )


class PostingInline(WorkspaceScopedInline):
    model = Posting
    formset = PostingFormSet


class LineItemInline(WorkspaceScopedInline):
    model = LineItem


class PrivateFileMixin:
    """Private files have no URL, so use a plain file input that never links to one."""

    formfield_overrides = {models.FileField: {"widget": forms.FileInput}}


class AttachmentInline(PrivateFileMixin, WorkspaceScopedInline):
    model = Attachment


@admin.register(Transaction)
class TransactionAdmin(WorkspaceScopedAdmin):
    list_display = ("date", "kind", "description", "merchant", "book", "status", "workspace")
    list_filter = ("status", "kind", "mode")
    search_fields = ("description", "utr")
    date_hierarchy = "date"
    readonly_fields = ("client_uuid",)
    filter_horizontal = ("tags",)
    inlines = [PostingInline, LineItemInline, AttachmentInline]


@admin.register(Posting)
class PostingAdmin(WorkspaceScopedAdmin):
    list_display = ("transaction", "account", "amount", "category", "person", "funding_owner")
    search_fields = ("account__name", "transaction__description")


@admin.register(LineItem)
class LineItemAdmin(WorkspaceScopedAdmin):
    list_display = ("name", "amount", "qty", "category", "transaction")
    search_fields = ("name",)


@admin.register(Attachment)
class AttachmentAdmin(PrivateFileMixin, WorkspaceScopedAdmin):
    list_display = ("transaction", "kind", "file_name", "created_at")
    list_filter = ("kind",)

    @admin.display(description="File")
    def file_name(self, obj):
        return obj.file.name


@admin.register(AuditLog)
class AuditLogAdmin(WorkspaceScopedAdmin):
    """The audit trail is read-only: it is written by services, never edited."""

    list_display = ("created_at", "action", "content_type", "object_id", "field", "actor")
    list_filter = ("action", "content_type")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
