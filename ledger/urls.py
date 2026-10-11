from django.urls import path

from . import views

urlpatterns = [
    path("entries/", views.EntriesView.as_view(), name="entries"),
    path("entries/add/", views.EntryAddView.as_view(), name="entry_add"),
    path("people/", views.PeopleView.as_view(), name="people"),
]
