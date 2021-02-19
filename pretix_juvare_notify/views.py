from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.generic import FormView
from pretix.base.models.organizer import Organizer
from pretix.control.permissions import (
    AdministratorPermissionRequiredMixin,
    OrganizerPermissionRequiredMixin,
)
from pretix.control.views.organizer import OrganizerDetailViewMixin

from .forms import JuvareGlobalSettingsForm, JuvareOrganizerSettingsForm


class OrganizerSettings(
    OrganizerDetailViewMixin, OrganizerPermissionRequiredMixin, FormView
):
    model = Organizer
    permission = "can_change_organizer_settings"
    form_class = JuvareOrganizerSettingsForm
    template_name = "pretix_juvare_notify/organizer.html"

    def get_context_data(self, **kwargs):
        result = super().get_context_data(**kwargs)
        result["has_client_secret"] = bool(
            self.request.organizer.settings.juvare_client_secret
        )
        return result

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["obj"] = self.request.organizer
        return kwargs

    def get_success_url(self, **kwargs):
        return reverse(
            "plugins:pretix_juvare_notify:organizer-settings",
            kwargs={
                "organizer": self.request.organizer.slug,
            },
        )

    def post(self, request, *args, **kwargs):
        form = self.get_form()
        if form.is_valid():
            form.save()
            messages.success(self.request, _("Your changes have been saved."))
            return redirect(self.get_success_url())
        messages.error(
            self.request, _("We could not save your changes. See below for details.")
        )
        return self.get(request)


class GlobalSettings(AdministratorPermissionRequiredMixin, FormView):
    form_class = JuvareGlobalSettingsForm
    template_name = "pretix_juvare_notify/global.html"

    def post(self, request, *args, **kwargs):
        form = self.get_form()
        if form.is_valid():
            form.save()
            messages.success(self.request, _("Your changes have been saved."))
            return redirect(self.get_success_url())
        messages.error(
            self.request, _("We could not save your changes. See below for details.")
        )
        return self.get(request)

    def get_context_data(self, **kwargs):
        result = super().get_context_data(**kwargs)
        return result

    def get_success_url(self, **kwargs):
        return reverse(
            "plugins:pretix_juvare_notify:global-settings",
        )
