from django.db import models
from django.utils.translation import gettext_lazy as _, pgettext_lazy
from django_scopes import ScopedManager
from pretix.base.models.event import SubEvent


class SubEventReminder(models.Model):
    subevent = models.ForeignKey(
        SubEvent,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        verbose_name=pgettext_lazy("subevent", "Date"),
        related_name="juvare_reminder",
    )
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)
    STATUS_STARTED = "s"
    STATUS_FINISHED = "f"
    STATUS_CHOICE = (
        (STATUS_STARTED, _("started")),
        (STATUS_FINISHED, _("finished")),
    )
    status = models.CharField(
        max_length=3,
        choices=STATUS_CHOICE,
        verbose_name=_("Status"),
        default="s",
        db_index=True,
    )
    objects = ScopedManager(organizer="subevent__event__organizer")
