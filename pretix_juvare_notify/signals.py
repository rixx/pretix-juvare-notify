import datetime as dt
from decimal import Decimal
from django.db.models import Exists, OuterRef
from django.dispatch import receiver
from django.urls import resolve, reverse
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _
from django_scopes import scopes_disabled
from i18nfield.strings import LazyI18nString
from pretix.base.email import get_email_context
from pretix.base.i18n import language
from pretix.base.services.mail import render_mail
from pretix.base.settings import settings_hierarkey
from pretix.base.signals import (
    logentry_display,
    order_canceled,
    order_changed,
    order_paid,
    order_placed,
    periodic_task,
)
from pretix.control.signals import (
    nav_event,
    nav_event_settings,
    nav_global,
    nav_organizer,
)

from .tasks import send_subevent_reminders

JUVARE_TEMPLATES = [
    "juvare_text_signature",
    "juvare_text_order_placed",
    "juvare_text_order_free",
    "juvare_text_order_changed",
    "juvare_text_order_canceled",
    "juvare_text_order_paid",
    "juvare_reminder_text",
]

for settings_name in JUVARE_TEMPLATES:
    settings_hierarkey.add_default(settings_name, "", LazyI18nString)
settings_hierarkey.add_default("juvare_send_reminders", "false", bool)
settings_hierarkey.add_default("juvare_reminder_interval", "0", int)
settings_hierarkey.add_default("juvare_reminder_interval_cutoff", "0", int)


@receiver(nav_organizer, dispatch_uid="juvare_nav_organizer")
def navbar_organizer(sender, request, **kwargs):
    if not request.user.has_organizer_permission(
        request.organizer, "can_change_organizer_settings", request
    ):
        return []
    url = resolve(request.path_info)
    return [
        {
            "label": "Juvare Notify",
            "url": reverse(
                "plugins:pretix_juvare_notify:organizer-settings",
                kwargs={
                    "organizer": request.organizer.slug,
                },
            ),
            "icon": "mobile-phone",
            "active": url.namespace == "plugins:pretix_juvare_notify"
            and "settings" in url.url_name,
        }
    ]


@receiver(nav_event_settings, dispatch_uid="juvare_nav_event_settings")
def navbar_event_settings(sender, request, **kwargs):
    if not request.user.has_organizer_permission(
        request.organizer, "can_change_organizer_settings", request
    ):
        return []
    url = resolve(request.path_info)
    return [
        {
            "label": "Juvare Notify Settings",
            "url": reverse(
                "plugins:pretix_juvare_notify:organizer-settings",
                kwargs={
                    "organizer": request.organizer.slug,
                },
            ),
            "active": url.namespace == "plugins:pretix_juvare_notify"
            and "settings" in url.url_name,
        }
    ]


@receiver(nav_global, dispatch_uid="juvare_nav_global")
def navbar_global(sender, request, **kwargs):
    if not request.user.is_staff:
        return []
    url = resolve(request.path_info)
    return [
        {
            "label": "Juvare Notify",
            "url": reverse(
                "plugins:pretix_juvare_notify:global-settings",
            ),
            "icon": "mobile-phone",
            "active": url.namespace == "plugins:pretix_juvare_notify"
            and "settings" in url.url_name,
        }
    ]


@receiver(nav_event, dispatch_uid="juvare_nav_sendsms")
def control_nav_import(sender, request=None, **kwargs):
    url = resolve(request.path_info)
    if not request.user.has_event_permission(
        request.organizer, request.event, "can_change_orders", request=request
    ):
        return []
    return [
        {
            "label": _("Send out SMS"),
            "url": reverse(
                "plugins:pretix_juvare_notify:send",
                kwargs={
                    "event": request.event.slug,
                    "organizer": request.event.organizer.slug,
                },
            ),
            "active": (
                url.namespace == "plugins:pretix_juvare_notify"
                and url.url_name == "send"
            ),
            "icon": "mobile-phone",
            "children": [
                {
                    "label": _("Send SMS"),
                    "url": reverse(
                        "plugins:pretix_juvare_notify:send",
                        kwargs={
                            "event": request.event.slug,
                            "organizer": request.event.organizer.slug,
                        },
                    ),
                    "active": (
                        url.namespace == "plugins:pretix_juvare_notify"
                        and url.url_name == "send"
                    ),
                },
                {
                    "label": _("SMS history"),
                    "url": reverse(
                        "plugins:pretix_juvare_notify:history",
                        kwargs={
                            "event": request.event.slug,
                            "organizer": request.event.organizer.slug,
                        },
                    ),
                    "active": (
                        url.namespace == "plugins:pretix_juvare_notify"
                        and url.url_name == "history"
                    ),
                },
                {
                    "label": "Reminders",
                    "url": reverse(
                        "plugins:pretix_juvare_notify:reminders",
                        kwargs={
                            "organizer": request.organizer.slug,
                            "event": request.event.slug,
                        },
                    ),
                    "active": url.namespace == "plugins:pretix_juvare_notify"
                    and url.url_name == "reminders",
                },
            ],
        },
    ]


@receiver(signal=logentry_display)
def pretixcontrol_logentry_display(sender, logentry, **kwargs):
    plains = {
        "pretix.plugins.pretix_juvare_notify.sent": _("SMS was sent"),
        "pretix.plugins.pretix_juvare_notify.order.sms.sent": _(
            "The order received a mass SMS."
        ),
        "pretix.plugins.pretix_juvare_notify.order.sms.sent.attendee": _(
            "A ticket holder of this order received a mass SMS."
        ),
    }
    if logentry.action_type in plains:
        return plains[logentry.action_type]


def juvare_order_message(order, template_name):
    from .tasks import juvare_send

    recipient = order.phone
    if not order.phone:
        return

    context = get_email_context(event=order.event, order=order)
    for k, v in order.event.meta_data.items():
        context["meta_" + k] = v

    with language(order.locale, order.event.settings.region):
        template = order.event.settings.get(f"juvare_text_{template_name}")
        if not str(template):
            return

        try:
            content = render_mail(template, context)
            juvare_send(text=content, to=str(recipient), event=order.event_id)
        except Exception:
            raise
        else:
            order.log_action(
                "pretix_juvare_notify.message.sent",
                data={
                    "message": content,
                    "recipient": str(recipient),
                    "order": order.code,
                },
            )


@receiver(order_placed, dispatch_uid="juvare_order_placed")
def juvare_order_placed(order, sender, **kwargs):
    payment = order.payments.first()
    if (
        payment
        and payment.provider == "free"
        and order.pending_sum == Decimal("0.00")
        and not order.require_approval
    ):
        juvare_order_message(order, "order_free")
    else:
        juvare_order_message(order, "order_placed")


@receiver(order_paid, dispatch_uid="juvare_order_paid")
def juvare_order_paid(order, sender, **kwargs):
    juvare_order_message(order, "order_paid")


@receiver(order_canceled, dispatch_uid="juvare_order_canceled")
def juvare_order_canceled(order, sender, **kwargs):
    juvare_order_message(order, "order_canceled")


@receiver(order_changed, dispatch_uid="juvare_order_changed")
def juvare_order_changed(order, sender, **kwargs):
    juvare_order_message(order, "order_changed")


@receiver(periodic_task, dispatch_uid="juvare_periodic_reminder")
def juvare_periodic_reminder(*args, **kwargs):
    from pretix.base.models.event import Event, Event_SettingsStore, SubEvent

    with scopes_disabled():
        active_events = (
            Event.objects.filter(subevents__isnull=False)
            .distinct()
            .annotate(
                send_reminders=Exists(
                    Event_SettingsStore.objects.filter(
                        key="juvare_send_reminders",
                        value="True",
                        object_id=OuterRef("pk"),
                    )
                )
            )
            .filter(send_reminders=True)
        )
        _now = now()
        for subevent in SubEvent.objects.filter(
            event__in=active_events, juvare_reminder__isnull=True, date_from__gt=_now
        ):
            if _now > subevent.date_from - dt.timedelta(
                hours=int(subevent.event.settings.juvare_reminder_interval)
            ) and _now < subevent.date_from - dt.timedelta(
                hours=int(subevent.event.settings.juvare_reminder_interval_cutoff)
            ):
                send_subevent_reminders.apply_async(kwargs={"subevent": subevent.pk})
