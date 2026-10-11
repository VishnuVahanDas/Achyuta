"""Business logic for the core app. Views call these; they never write models directly."""

from .models import Workspace


def workspace_for(user):
    """Return the user's workspace, creating it on first use.

    Each user owns exactly one workspace and can never see another's.
    """
    workspace, _ = Workspace.objects.get_or_create(
        owner=user,
        defaults={"name": user.get_full_name() or user.get_username()},
    )
    return workspace
