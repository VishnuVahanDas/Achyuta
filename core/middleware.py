from . import services


class WorkspaceMiddleware:
    """Attach request.workspace: the logged-in user's workspace, or None when anonymous.

    Must run after AuthenticationMiddleware. Views scope every query by it.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.workspace = (
            services.workspace_for(request.user) if request.user.is_authenticated else None
        )
        return self.get_response(request)
