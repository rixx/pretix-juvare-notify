import csv
import pathlib
import sys
from django.core.management.base import BaseCommand
from django_scopes import scopes_disabled
from pretix.base.models.log import LogEntry
from pretix.multidomain.urlreverse import build_absolute_uri


class Command(BaseCommand):
    help = "Exports logs of sent bulk messages with recipient/URL mismatches."

    def add_arguments(self, parser):
        parser.add_argument(
            "--with-messages",
            action="store_true",
            help="Include full messages in the export",
        )
        parser.add_argument(
            "--location",
            help="Place the file here instead of writing to stdout",
            default=None,
        )

    @scopes_disabled()
    def handle(self, *args, **options):
        export_messages = options.get("with_messages")
        location = options.get("location")
        all_bulk_send_logs = LogEntry.objects.filter(
            action_type="pretix.plugins.pretix_juvare_notify.order.sms.sent"
        ).select_related("event")
        print(f"Total sent bulk SMS: {len(all_bulk_send_logs)}")

        broken_recipient = []
        broken_url = []

        for log in all_bulk_send_logs:
            order = log.content_object
            content = log.parsed_data.get("message")
            if not content:
                continue
            if log.parsed_data.get("recipient") != order.phone:
                broken_recipient.append(
                    {
                        "order": order.code,
                        "event": log.event.slug,
                        "order.phone": order.phone,
                        "recipient": log.parsed_data.get("recipient"),
                        "timestamp": log.datetime.isoformat(),
                        "message": log.parsed_data.get("message"),
                    }
                )
            if "https://" in content:
                target_url = build_absolute_uri(
                    log.event,
                    "presale:event.order.open",
                    kwargs={
                        "order": order.code,
                        "secret": order.secret,
                        "hash": order.email_confirm_hash(),
                    },
                )
                if target_url not in content:
                    broken_url.append(
                        {
                            "order": order.code,
                            "event": log.event.slug,
                            "order.phone": order.phone,
                            "recipient": log.parsed_data.get("recipient"),
                            "timestamp": log.datetime.isoformat(),
                            "correct_url": target_url,
                            "message": log.parsed_data.get("message"),
                        }
                    )
                    broken_url.append((log, order, target_url))

        def write(fieldnames, data, filename, location):
            if location:
                with open(pathlib.Path(location) / filename, "w") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(data)
            else:
                writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(data)

        print(
            f"Total SMS where the recipient does not match order.phone: {len(broken_recipient)}"
        )
        if broken_recipient:
            fieldnames = ["order", "event", "order.phone", "recipient", "timestamp"]
            if export_messages:
                fieldnames.append("message")
            write(fieldnames, broken_recipient, "broken_recipients.csv", location)

        print(
            f"Total SMS where an included URL does not match order's URL: {len(broken_url)}"
        )
        if broken_url:
            fieldnames = [
                "order",
                "event",
                "order.phone",
                "recipient",
                "timestamp",
                "correct_url",
            ]
            if export_messages:
                fieldnames.append("message")
            write(fieldnames, broken_url, "broken_urls.csv", location)
