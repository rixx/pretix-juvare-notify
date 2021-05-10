import json
import logging
import requests
from django.db.models import Exists, OuterRef
from django_scopes import scope, scopes_disabled
from i18nfield.strings import LazyI18nString
from pretix.base.email import get_email_context
from pretix.base.i18n import language
from pretix.base.models import (
    Event,
    InvoiceAddress,
    Order,
    OrderPosition,
    Organizer,
    SubEvent,
    User,
)
from pretix.base.services.mail import TolerantDict
from pretix.celery_app import app

logger = logging.getLogger(__name__)


@app.task()
def juvare_send_task(text: str, to: str, event: int):
    if not (text and to and event):
        return

    with scopes_disabled():
        event = Event.objects.get(id=event)

    with scope(organizer=event.organizer):
        client_secret = event.settings.juvare_client_secret  # global setting
        url = (
            event.settings.juvare_api_url or "https://notify.lab.juvare.com/manage/"
        )  # global setting
        if not (client_secret and url):
            return

        if url[-1] != "/":
            url += "/"
        url += "api/v3/notification"

        to = to.replace(" ", "")
        if event.settings.juvare_text_signature:
            text = f"{text}\n\n{event.settings.juvare_text_signature}"

        body = [
            {
                "type": "sms",
                "addresses": [to],
                "message": text,
                "repeatCount": 0,
                "repeatDelay": 0,
                "billingId": event.settings.juvare_billing_id,
            }
        ]
        response = requests.post(
            url,
            data=json.dumps(body),
            headers={
                "accept": "application/json",
                "x-client-secret": client_secret,
                "Content-Type": "application/json",
            },
        )
        try:
            response.raise_for_status()
            message = f"SUCCESS: Sent Juvare Notify message with billing ID: {body[0]['billingId']} for {event.slug}. "
            try:
                content = response.json()
                if content:
                    message += f"Response: {content}"
                else:
                    message += "No details were provided."
            except Exception:
                message += "No details were provided."
            logger.info(message)
        except Exception as e:
            message = f"Failed to send Juvare Notify message with billing ID {body[0]['billingId']} for {event.slug}. "
            message += f"Error: {e}. "
            message += f"Received API response {response.status_code}."
            try:
                content = response.json()
                if content and isinstance(content, dict) and content.get("message"):
                    message += f"It said: {content['message']}"
                else:
                    message += "It contained no further message to explain the error."
            except Exception:
                message += "It had no readable JSON body with details."
            logger.error(message)


def juvare_send(*args, **kwargs):
    juvare_send_task.apply_async(args=args, kwargs=kwargs)


@app.task(acks_late=True)
def send_bulk_sms(event: Event, user: int, message: dict, orders: list) -> None:
    with scopes_disabled():
        event = Event.objects.all().select_related("organizer").get(pk=event)

    with scope(organizer=event.organizer):
        print(orders)
        orders = Order.objects.filter(pk__in=orders, event=event)
        message = LazyI18nString(message)
        user = User.objects.get(pk=user) if user else None
        print(orders)
        for o in orders:

            if o.phone:
                try:
                    ia = o.invoice_address
                except InvoiceAddress.DoesNotExist:
                    ia = InvoiceAddress(order=o)

                try:
                    with language(o.locale, event.settings.region):
                        email_context = get_email_context(
                            event=event, order=o, position_or_address=ia
                        )
                        message = str(message).format_map(TolerantDict(email_context))
                        juvare_send(text=message, to=str(o.phone), event=event.pk)
                        o.log_action(
                            "pretix.plugins.pretix_juvare_notify.order.sms.sent",
                            user=user,
                            data={"message": message, "recipient": str(o.phone)},
                        )
                except Exception as e:
                    logger.error(
                        f"Failed to send part of a bulk message for order {o.code} ({event.slug}):\n{e}"
                    )


@app.task()
def send_subevent_reminders(subevent: int):
    from .models import SubEventReminder

    with scope(
        organizer=Organizer.objects.filter(events__subevents__pk=subevent).first()
    ):
        subevent = SubEvent.objects.get(pk=subevent)
        status, created = SubEventReminder.objects.get_or_create(subevent=subevent)
        if not created:
            return
        opq = OrderPosition.objects.filter(
            order=OuterRef("pk"),
            canceled=False,
            subevent=subevent,
        )
        orders = (
            Order.objects.filter(phone__isnull=False, event=subevent.event)
            .annotate(match_pos=Exists(opq))
            .filter(match_pos=True)
            .distinct()
        )
        orders = orders.values_list("pk", flat=True)
        if orders:
            send_bulk_sms.apply_async(
                kwargs={
                    "user": None,
                    "orders": list(orders),
                    "message": subevent.event.settings.juvare_reminder_text.data,
                    "event": subevent.event.pk,
                }
            )
        status.status = "f"
        status.save()
