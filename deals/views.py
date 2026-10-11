from django.views.generic import TemplateView


class DealsView(TemplateView):
    template_name = "deals/deals.html"
    extra_context = {"active_tab": "deals"}
