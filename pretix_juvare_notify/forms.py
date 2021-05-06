from django import forms
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils.translation import gettext_lazy as _, pgettext_lazy
from i18nfield.forms import I18nFormField, I18nTextarea
from pretix.base.email import get_available_placeholders
from pretix.base.forms import PlaceholderValidator, SettingsForm
from pretix.base.forms.widgets import SplitDateTimePickerWidget
from pretix.base.models import Item, Order, SubEvent
from pretix.base.settings import GlobalSettingsObject
from pretix.control.forms.widgets import Select2


class JuvareGlobalSettingsForm(SettingsForm):
    juvare_api_url = forms.URLField(
        label=_("API URL"),
        help_text=_(
            "Leave empty to use https://notify.lab.juvare.com/manage/. To send messages, '/api/v3/notification' will be appended."
        ),
        required=True,
    )
    juvare_client_secret = forms.CharField(
        label=_("Client secret"),
        required=False,
        help_text=_(
            "This client secret will be used for all events to send out SMS messages, if enabled."
        ),
        widget=forms.PasswordInput(
            attrs={
                "autocomplete": "new-password"  # see https://bugs.chromium.org/p/chromium/issues/detail?id=370363#c7
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        self.obj = GlobalSettingsObject()
        super().__init__(*args, obj=self.obj, **kwargs)
        if self.obj.settings.juvare_client_secret:
            self.fields["juvare_client_secret"].widget.attrs[
                "placeholder"
            ] = "•••••••••••"

    def clean(self):
        data = super().clean()
        if not data.get("juvare_client_secret"):
            data["juvare_client_secret"] = self.initial.get("juvare_client_secret")
        return data


class JuvareOrganizerSettingsForm(SettingsForm):
    juvare_billing_id = forms.CharField(
        label=_("Billing ID"),
        required=True,
    )
    juvare_text_signature = I18nFormField(
        label=_("Signature"),
        required=False,
        widget=I18nTextarea,
        help_text=_("This will be attached to every SMS."),
        validators=[PlaceholderValidator(["{event}"])],
        widget_kwargs={
            "attrs": {"rows": "4", "placeholder": _("e.g. your contact details")}
        },
    )
    juvare_text_order_placed = I18nFormField(
        label=_("Text sent to order contact address"),
        required=False,
        widget=I18nTextarea,
    )
    juvare_text_order_paid = I18nFormField(
        label=_("Text sent to order contact address"),
        required=False,
        widget=I18nTextarea,
    )
    juvare_text_order_free = I18nFormField(
        label=_("Text sent to order contact address"),
        required=False,
        widget=I18nTextarea,
    )
    juvare_text_order_changed = I18nFormField(
        label=_("Text"),
        required=False,
        widget=I18nTextarea,
    )
    juvare_text_order_canceled = I18nFormField(
        label=_("Text"),
        required=False,
        widget=I18nTextarea,
    )
    base_context = {
        "juvare_text_order_placed": ["event", "order", "payment"],
        "juvare_text_order_free": ["event", "order"],
        "juvare_text_order_changed": ["event", "order"],
        "juvare_text_order_canceled": ["event", "order"],
        "juvare_text_order_paid": ["event", "order", "payment_info"],
    }

    def _set_field_placeholders(self, fn, base_parameters):
        # from pretix.base.email import get_available_placeholders
        phs = [
            "{%s}" % p
            for p in [
                "event",
                "event_slug",
                "code",
                "total",
                "currency",
                "total_with_currency",
                "expire_date",
                "url",
                "url_info_change",
                "url_products_change",
                "url_cancel",
                "name",
            ]
            # if we had an event: get_available_placeholders(Event(organizer=self.organizer), base_parameters).keys()
        ]
        ht = _("Available placeholders: {list}").format(list=", ".join(phs))
        if self.fields[fn].help_text:
            self.fields[fn].help_text += " " + str(ht)
        else:
            self.fields[fn].help_text = ht
        self.fields[fn].validators.append(PlaceholderValidator(phs))

    def __init__(self, *args, **kwargs):
        self.organizer = kwargs.get("obj")
        super().__init__(*args, **kwargs)
        for k, v in self.base_context.items():
            self._set_field_placeholders(k, v)


class SMSForm(forms.Form):
    """Heavily copied from pretix.plugins.sendmail.forms.MailForm."""

    sendto = forms.MultipleChoiceField()  # overridden later
    message = forms.CharField(label=_("Message"))
    items = forms.ModelMultipleChoiceField(
        widget=forms.CheckboxSelectMultiple(
            attrs={"class": "scrolling-multiple-choice"}
        ),
        label=_("Only send to people who bought"),
        required=True,
        queryset=Item.objects.none(),
    )
    subevent = forms.ModelChoiceField(
        SubEvent.objects.none(),
        label=_("Only send to customers of"),
        required=False,
        empty_label=pgettext_lazy("subevent", "All dates"),
    )
    subevents_from = forms.SplitDateTimeField(
        widget=SplitDateTimePickerWidget(),
        label=pgettext_lazy(
            "subevent", "Only send to customers of dates starting at or after"
        ),
        required=False,
    )
    subevents_to = forms.SplitDateTimeField(
        widget=SplitDateTimePickerWidget(),
        label=pgettext_lazy(
            "subevent", "Only send to customers of dates starting before"
        ),
        required=False,
    )
    created_from = forms.SplitDateTimeField(
        widget=SplitDateTimePickerWidget(),
        label=pgettext_lazy(
            "subevent", "Only send to customers with orders created after"
        ),
        required=False,
    )
    created_to = forms.SplitDateTimeField(
        widget=SplitDateTimePickerWidget(),
        label=pgettext_lazy(
            "subevent", "Only send to customers with orders created before"
        ),
        required=False,
    )

    def clean(self):
        d = super().clean()
        if d.get("subevent") and (d.get("subevents_from") or d.get("subevents_to")):
            raise ValidationError(
                pgettext_lazy(
                    "subevent",
                    "Please either select a specific date or a date range, not both.",
                )
            )
        if bool(d.get("subevents_from")) != bool(d.get("subevents_to")):
            raise ValidationError(
                pgettext_lazy(
                    "subevent",
                    "If you set a date range, please set both a start and an end.",
                )
            )
        return d

    def _set_field_placeholders(self, fn, base_parameters):
        phs = [
            "{%s}" % p
            for p in sorted(
                get_available_placeholders(self.event, base_parameters).keys()
            )
        ]
        ht = _("Available placeholders: {list}").format(list=", ".join(phs))
        if self.fields[fn].help_text:
            self.fields[fn].help_text += " " + str(ht)
        else:
            self.fields[fn].help_text = ht
        self.fields[fn].validators.append(PlaceholderValidator(phs))

    def __init__(self, *args, **kwargs):
        event = self.event = kwargs.pop("event")
        super().__init__(*args, **kwargs)

        self.fields["message"] = I18nFormField(
            label=_("Message"),
            widget=I18nTextarea,
            required=True,
            locales=event.settings.get("locales"),
        )
        self._set_field_placeholders(
            "message", ["event", "order", "position_or_address"]
        )
        choices = [(e, l) for e, l in Order.STATUS_CHOICE if e != "n"]
        choices.insert(0, ("na", _("payment pending (except unapproved)")))
        choices.insert(0, ("pa", _("approval pending")))
        if not event.settings.get("payment_term_expire_automatically", as_type=bool):
            choices.append(("overdue", _("pending with payment overdue")))
        self.fields["sendto"] = forms.MultipleChoiceField(
            label=_("Send to customers with order status"),
            widget=forms.CheckboxSelectMultiple(
                attrs={"class": "scrolling-multiple-choice"}
            ),
            choices=choices,
        )
        if not self.initial.get("sendto"):
            self.initial["sendto"] = ["p", "na"]
        elif "n" in self.initial["sendto"]:
            self.initial["sendto"].append("pa")
            self.initial["sendto"].append("na")

        self.fields["items"].queryset = event.items.all()
        if not self.initial.get("items"):
            self.initial["items"] = event.items.all()

        if event.has_subevents:
            self.fields["subevent"].queryset = event.subevents.all()
            self.fields["subevent"].widget = Select2(
                attrs={
                    "data-model-select2": "event",
                    "data-select2-url": reverse(
                        "control:event.subevents.select2",
                        kwargs={
                            "event": event.slug,
                            "organizer": event.organizer.slug,
                        },
                    ),
                    "data-placeholder": pgettext_lazy("subevent", "Date"),
                }
            )
            self.fields["subevent"].widget.choices = self.fields["subevent"].choices
        else:
            del self.fields["subevent"]
            del self.fields["subevents_from"]
            del self.fields["subevents_to"]
