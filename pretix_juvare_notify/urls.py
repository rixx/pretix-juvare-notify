from django.conf.urls import url

from . import views

urlpatterns = [
    # url(
    #     r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/settings/juvare-notify$",
    #     views.EventSettings.as_view(),
    #     name="event-settings",
    # ),
    url(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/juvare-notify/$",
        views.SenderView.as_view(),
        name="send",
    ),
    url(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/juvare-notify/reminders$",
        views.ReminderView.as_view(),
        name="reminders",
    ),
    url(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/juvare-notify/history/",
        views.SMSHistoryView.as_view(),
        name="history",
    ),
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
