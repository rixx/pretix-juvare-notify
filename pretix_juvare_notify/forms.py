from django import forms
from django.utils.translation import gettext_lazy as _
from i18nfield.forms import I18nFormField, I18nTextarea
from pretix.base.forms import PlaceholderValidator, SettingsForm
from pretix.base.settings import GlobalSettingsObject


class JuvareGlobalSettingsForm(SettingsForm):
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
        data = self.cleaned_data
        if not data.get("juvare_client_secret"):
            data["juvare_client_secret"] = self.initial.get("juvare_client_secret")


class JuvareOrganizerSettingsForm(SettingsForm):
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
        phs = [
            "{%s}" % p
            for p in sorted(
                base_parameters
            )  # if we had an event: get_available_placeholders(Event(organizer=self.organizer), base_parameters).keys()
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
