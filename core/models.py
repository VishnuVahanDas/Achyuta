from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class TimestampedModel(models.Model):
    """Abstract base adding created/updated timestamps to every model."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class WorkspaceModel(TimestampedModel):
    """Abstract base for everything a user owns: a workspace FK plus timestamps."""

    workspace = models.ForeignKey("core.Workspace", on_delete=models.CASCADE)

    class Meta:
        abstract = True

    def clean(self):
        """Reject links to rows that belong to another workspace."""
        super().clean()
        if self.workspace_id is None:
            return
        errors = {}
        for field in self._meta.concrete_fields:
            if not field.many_to_one or field.name == "workspace":
                continue
            if getattr(self, field.attname) is None:
                continue
            related = getattr(self, field.name)
            if getattr(related, "workspace_id", self.workspace_id) != self.workspace_id:
                errors[field.name] = "This belongs to a different workspace."
        if errors:
            raise ValidationError(errors)


class User(AbstractUser):
    """Custom user so fields (PIN, TOTP, invites) can be added without a swap later."""


class Workspace(TimestampedModel):
    """One user's private set of books. Every other table carries a workspace FK."""

    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="workspace"
    )
    name = models.CharField(max_length=100)
    currency = models.CharField(max_length=3, default="INR")
    start_date = models.DateField(default=timezone.localdate)

    def __str__(self):
        return self.name
