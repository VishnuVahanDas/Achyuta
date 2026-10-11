from django.views.generic import TemplateView


class HomeView(TemplateView):
    template_name = "reports/home.html"
    extra_context = {"active_tab": "home"}
