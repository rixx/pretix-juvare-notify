import json
import logging
import requests
from django_scopes import scope, scopes_disabled
from pretix.base.models import Event
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
                    message += f"It contained no further message to explain the error."
            except Exception:
                message += "It had no readable JSON body with details."
            logger.error(message)


def juvare_send(*args, **kwargs):
    juvare_send_task.apply_async(args=args, kwargs=kwargs)
