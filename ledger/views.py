from django.views.generic import TemplateView


class EntriesView(TemplateView):
    template_name = "ledger/entries.html"
    extra_context = {"active_tab": "entries"}


class PeopleView(TemplateView):
    template_name = "ledger/people.html"
    extra_context = {"active_tab": "people"}


class EntryAddView(TemplateView):
    template_name = "ledger/entry_add.html"
