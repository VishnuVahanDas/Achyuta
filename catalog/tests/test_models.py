import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from catalog.models import Category, Merchant, Tag
from ledger.models import Account, PaymentApp

pytestmark = pytest.mark.django_db


@pytest.fixture
def food(workspace):
    return Category.objects.create(workspace=workspace, name="Food", kind="expense")


def test_sub_category_reads_as_parent_then_name(workspace, food):
    fruits = Category.objects.create(
        workspace=workspace, name="Fruits", kind="expense", parent=food
    )

    assert str(fruits) == "Food › Fruits"
    assert list(food.children.all()) == [fruits]


def test_categories_go_only_two_levels_deep(workspace, food):
    fruits = Category.objects.create(
        workspace=workspace, name="Fruits", kind="expense", parent=food
    )
    apple = Category(workspace=workspace, name="Apple", kind="expense", parent=fruits)

    with pytest.raises(ValidationError, match="two levels"):
        apple.full_clean()


def test_category_with_children_cannot_become_a_sub_category(workspace, food):
    Category.objects.create(workspace=workspace, name="Fruits", kind="expense", parent=food)
    travel = Category.objects.create(workspace=workspace, name="Travel", kind="expense")
    food.parent = travel

    with pytest.raises(ValidationError, match="cannot be nested"):
        food.full_clean()


def test_sub_category_must_match_its_parents_kind(workspace, food):
    salary = Category(workspace=workspace, name="Salary", kind="income", parent=food)

    with pytest.raises(ValidationError, match="same kind"):
        salary.full_clean()


def test_same_sub_category_name_is_allowed_under_different_parents(workspace, food):
    personal = Category.objects.create(workspace=workspace, name="Personal", kind="expense")
    learning = Category.objects.create(workspace=workspace, name="Learning", kind="expense")

    Category.objects.create(workspace=workspace, name="Books", kind="expense", parent=personal)
    Category.objects.create(workspace=workspace, name="Books", kind="expense", parent=learning)

    assert Category.objects.filter(name="Books").count() == 2


def test_duplicate_names_are_refused_at_each_level(workspace, food):
    Category.objects.create(workspace=workspace, name="Fruits", kind="expense", parent=food)

    with pytest.raises(IntegrityError), transaction.atomic():
        Category.objects.create(workspace=workspace, name="Food", kind="expense")
    with pytest.raises(IntegrityError), transaction.atomic():
        Category.objects.create(workspace=workspace, name="Fruits", kind="expense", parent=food)


def test_category_parent_must_be_in_the_same_workspace(other_workspace, food):
    fruits = Category(workspace=other_workspace, name="Fruits", kind="expense", parent=food)

    with pytest.raises(ValidationError, match="different workspace"):
        fruits.full_clean()


def test_catalog_names_are_unique_per_workspace_only(workspace, other_workspace, food):
    Tag.objects.create(workspace=workspace, name="bike")
    Merchant.objects.create(workspace=workspace, name="Blinkit")

    Tag.objects.create(workspace=other_workspace, name="bike")
    Merchant.objects.create(workspace=other_workspace, name="Blinkit")
    Category.objects.create(workspace=other_workspace, name="Food", kind="expense")

    with pytest.raises(IntegrityError), transaction.atomic():
        Tag.objects.create(workspace=workspace, name="bike")
    with pytest.raises(IntegrityError), transaction.atomic():
        Merchant.objects.create(workspace=workspace, name="Blinkit")


def test_merchant_remembers_its_defaults_and_survives_their_deletion(workspace, food):
    sbi = Account.objects.create(workspace=workspace, name="SBI", type="bank")
    phonepe = PaymentApp.objects.create(workspace=workspace, name="PhonePe", default_account=sbi)
    blinkit = Merchant.objects.create(
        workspace=workspace,
        name="Blinkit",
        default_category=food,
        default_payment_app=phonepe,
        default_account=sbi,
    )

    phonepe.delete()
    blinkit.refresh_from_db()

    assert blinkit.default_payment_app is None
    assert blinkit.default_category == food
    assert blinkit.default_account == sbi
