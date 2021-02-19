import json
import requests
from django_scopes import scope, scopes_disabled
from pretix.base.models import Event
from pretix.celery_app import app


@app.task()
def juvare_send_task(text: str, to: str, event: int):
    if not (text and to and event):
        return

    with scopes_disabled():
        event = Event.objects.get(id=event)

    with scope(organizer=event.organizer):
        client_secret = event.settings.juvare_client_secret  # global setting
        if not client_secret:
            return
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
            }
        ]
        requests.post(
            "https://notify.lab.juvare.com/manage/api/v3/notification",
            data=json.dumps(body),
            headers={
                "accept": "application/json",
                "x-client-secret": client_secret,
                "Content-Type": "application/json",
            },
        )


def juvare_send(*args, **kwargs):
    juvare_send_task.apply_async(args=args, kwargs=kwargs)
