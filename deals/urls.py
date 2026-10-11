from django.urls import path

from . import views

urlpatterns = [
    path("deals/", views.DealsView.as_view(), name="deals"),
]
