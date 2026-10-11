from django.contrib import admin

from core.admin import WorkspaceScopedAdmin

from .models import Category, Merchant, Tag


@admin.register(Category)
class CategoryAdmin(WorkspaceScopedAdmin):
    list_display = ("name", "parent", "kind", "workspace")
    list_filter = ("kind",)
    search_fields = ("name",)


@admin.register(Tag)
class TagAdmin(WorkspaceScopedAdmin):
    list_display = ("name", "workspace")
    search_fields = ("name",)


@admin.register(Merchant)
class MerchantAdmin(WorkspaceScopedAdmin):
    list_display = ("name", "default_category", "default_payment_app", "default_account")
    search_fields = ("name",)
