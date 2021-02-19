from django.conf.urls import url

from . import views

urlpatterns = [
    # url(
    #     r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/settings/juvare-notify$",
    #     views.EventSettings.as_view(),
    #     name="event-settings",
    # ),
    url(
        r"^control/event/(?P<organizer>[^/]+)/juvare-notify$",
        views.OrganizerSettings.as_view(),
        name="organizer-settings",
    ),
    url(
        r"^control/juvare-notify$",
        views.GlobalSettings.as_view(),
        name="global-settings",
    ),
]
