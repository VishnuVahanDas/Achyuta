from django.db import models


class MoneyField(models.DecimalField):
    """An amount of money: Decimal with 2 places. Use this for every amount, never float."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_digits", 14)
        kwargs.setdefault("decimal_places", 2)
        super().__init__(*args, **kwargs)
