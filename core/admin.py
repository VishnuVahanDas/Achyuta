from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User, Workspace, WorkspaceModel

admin.site.register(User, UserAdmin)


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "currency", "start_date")
    search_fields = ("name", "owner__username")


class WorkspaceChoicesMixin:
    """Limit every relation dropdown to rows of the workspace being edited.

    The workspace is that of the object on a change page. On an add page it is the
    one chosen in the form, else ?workspace=<id>, else the admin user's own.
    """

    def _workspace_id(self, request):
        if not hasattr(request, "_admin_workspace_id"):
            owner_model = getattr(self, "parent_model", self.model)
            object_id = request.resolver_match.kwargs.get("object_id")
            chosen = request.POST.get("workspace") or request.GET.get("workspace") or ""
            if object_id:
                workspace_id = (
                    owner_model._default_manager.filter(pk=object_id)
                    .values_list("workspace_id", flat=True)
                    .first()
                )
            elif chosen.isdigit():
                workspace_id = int(chosen)
            else:
                workspace_id = getattr(request.workspace, "pk", None)
            request._admin_workspace_id = workspace_id
        return request._admin_workspace_id

    def _scope(self, db_field, request, kwargs):
        related = db_field.related_model
        if db_field.name != "workspace" and issubclass(related, WorkspaceModel):
            base = kwargs.get("queryset", related._default_manager)
            kwargs["queryset"] = base.filter(workspace_id=self._workspace_id(request))

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        self._scope(db_field, request, kwargs)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        self._scope(db_field, request, kwargs)
        return super().formfield_for_manytomany(db_field, request, **kwargs)


class WorkspaceScopedAdmin(WorkspaceChoicesMixin, admin.ModelAdmin):
    """Base admin for workspace-owned models: filter by workspace, scope dropdowns."""

    def get_list_filter(self, request):
        return ("workspace", *super().get_list_filter(request))

    def get_changeform_initial_data(self, request):
        return {"workspace": request.workspace, **super().get_changeform_initial_data(request)}

    def save_formset(self, request, form, formset, change):
        # Inline rows always live in their parent's workspace.
        for obj in formset.save(commit=False):
            obj.workspace = form.instance.workspace
            obj.save()
        for obj in formset.deleted_objects:
            obj.delete()
        formset.save_m2m()


class WorkspaceScopedInline(WorkspaceChoicesMixin, admin.TabularInline):
    exclude = ("workspace",)
    extra = 0
