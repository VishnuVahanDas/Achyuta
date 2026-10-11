from django.views.generic import TemplateView


class MoreView(TemplateView):
    template_name = "core/more.html"
    extra_context = {"active_tab": "more"}
