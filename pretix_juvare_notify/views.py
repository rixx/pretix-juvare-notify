import logging
from django.contrib import messages
from django.db.models import Exists, OuterRef, Q
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _
from django.views.generic import FormView, ListView
from pretix.base.email import get_available_placeholders
from pretix.base.i18n import language
from pretix.base.models import LogEntry, Order, OrderPosition
from pretix.base.models.event import SubEvent
from pretix.base.models.organizer import Organizer
from pretix.base.services.mail import TolerantDict
from pretix.base.templatetags.rich_text import markdown_compile_email
from pretix.control.permissions import (
    AdministratorPermissionRequiredMixin,
    EventPermissionRequiredMixin,
    OrganizerPermissionRequiredMixin,
)
from pretix.control.views.organizer import OrganizerDetailViewMixin

from .forms import JuvareReminderSettingsForm, SMSForm
from .models import SubEventReminder
from .tasks import send_bulk_sms

logger = logging.getLogger("pretix.plugins.sendmail")

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


class SenderView(EventPermissionRequiredMixin, FormView):
    template_name = "pretix_juvare_notify/send_form.html"
    permission = "can_change_orders"
    form_class = SMSForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["event"] = self.request.event
        return kwargs

    def form_invalid(self, form):
        messages.error(
            self.request, _("We could not send the email. See below for details.")
        )
        return super().form_invalid(form)

    def form_valid(self, form):
        qs = Order.objects.filter(event=self.request.event)
        statusq = Q(status__in=form.cleaned_data["sendto"])
        if "overdue" in form.cleaned_data["sendto"]:
            statusq |= Q(status=Order.STATUS_PENDING, expires__lt=now())
        if "pa" in form.cleaned_data["sendto"]:
            statusq |= Q(status=Order.STATUS_PENDING, require_approval=True)
        if "na" in form.cleaned_data["sendto"]:
            statusq |= Q(status=Order.STATUS_PENDING, require_approval=False)
        orders = qs.filter(statusq)

        opq = OrderPosition.objects.filter(
            order=OuterRef("pk"),
            canceled=False,
            item_id__in=[i.pk for i in form.cleaned_data.get("items")],
        )

        if form.cleaned_data.get("filter_checkins"):
            ql = []
            if form.cleaned_data.get("not_checked_in"):
                ql.append(Q(checkins__list_id=None))
            if form.cleaned_data.get("checkin_lists"):
                ql.append(
                    Q(
                        checkins__list_id__in=[
                            i.pk for i in form.cleaned_data.get("checkin_lists", [])
                        ],
                    )
                )
            if len(ql) == 2:
                opq = opq.filter(ql[0] | ql[1])
            elif ql:
                opq = opq.filter(ql[0])
            else:
                opq = opq.none()

        if form.cleaned_data.get("subevent"):
            opq = opq.filter(subevent=form.cleaned_data.get("subevent"))
        if form.cleaned_data.get("subevents_from"):
            opq = opq.filter(
                subevent__date_from__gte=form.cleaned_data.get("subevents_from")
            )
        if form.cleaned_data.get("subevents_to"):
            opq = opq.filter(
                subevent__date_from__lt=form.cleaned_data.get("subevents_to")
            )
        if form.cleaned_data.get("created_from"):
            opq = opq.filter(order__datetime__gte=form.cleaned_data.get("created_from"))
        if form.cleaned_data.get("created_to"):
            opq = opq.filter(order__datetime__lt=form.cleaned_data.get("created_to"))
        if form.cleaned_data.get("items"):
            opq = opq.filter(item__in=form.cleaned_data["items"])

        orders = (
            orders.annotate(match_pos=Exists(opq)).filter(match_pos=True).distinct()
        )

        self.output = {}
        if not orders:
            messages.error(
                self.request, _("There are no orders matching this selection.")
            )
            return self.get(self.request, *self.args, **self.kwargs)

        if self.request.POST.get("action") == "preview":
            for loc in self.request.event.settings.locales:
                with language(loc, self.request.event.settings.region):
                    context_dict = TolerantDict()
                    for k, v in get_available_placeholders(
                        self.request.event, ["event", "order", "position_or_address"]
                    ).items():
                        context_dict[
                            k
                        ] = '<span class="placeholder" title="{}">{}</span>'.format(
                            _(
                                "This value will be replaced based on dynamic parameters."
                            ),
                            v.render_sample(self.request.event),
                        )

                    message = form.cleaned_data["message"].localize(loc)
                    preview_text = markdown_compile_email(
                        message.format_map(context_dict)
                    )

                    self.output[loc] = {
                        "html": preview_text,
                    }

            return self.get(self.request, *self.args, **self.kwargs)

        kwargs = {
            "event": self.request.event.pk,
            "user": self.request.user.pk,
            "message": form.cleaned_data["message"].data,
            "orders": [o.pk for o in orders],
        }

        send_bulk_sms.apply_async(kwargs=kwargs)
        self.request.event.log_action(
            "pretix.plugins.pretix_juvare_notify.sent",
            user=self.request.user,
            data=dict(form.cleaned_data),
        )
        messages.success(
            self.request,
            _(
                "Your message has been queued and will be sent to the contact addresses of %d "
                "orders in the next few minutes."
            )
            % len(orders),
        )

        return redirect(
            "plugins:pretix_juvare_notify:send",
            event=self.request.event.slug,
            organizer=self.request.event.organizer.slug,
        )

    def get_context_data(self, *args, **kwargs):
        ctx = super().get_context_data(*args, **kwargs)
        ctx["output"] = getattr(self, "output", None)
        ctx["has_client_secret"] = bool(
            self.request.organizer.settings.juvare_client_secret
        )
        return ctx


class SMSHistoryView(EventPermissionRequiredMixin, ListView):
    template_name = "pretix_juvare_notify/history.html"
    permission = "can_change_orders"
    model = LogEntry
    context_object_name = "logs"
    paginate_by = 5

    def get_queryset(self):
        qs = LogEntry.objects.filter(
            event=self.request.event,
            action_type="pretix.plugins.pretix_juvare_notify.sent",
        ).select_related("event", "user")
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data()

        itemcache = {i.pk: str(i) for i in self.request.event.items.all()}
        checkin_list_cache = {
            i.pk: str(i) for i in self.request.event.checkin_lists.all()
        }
        status = dict(Order.STATUS_CHOICE)
        status["overdue"] = _("pending with payment overdue")
        status["na"] = _("payment pending (except unapproved)")
        status["pa"] = _("approval pending")
        status["r"] = status["c"]
        for log in ctx["logs"]:
            log.pdata = log.parsed_data
            log.pdata["locales"] = {}
            for locale, msg in log.pdata["message"].items():
                log.pdata["locales"][locale] = {
                    "message": msg,
                }
            log.pdata["sendto"] = [status[s] for s in log.pdata["sendto"]]
            log.pdata["items"] = [
                itemcache.get(i["id"], "?") for i in log.pdata.get("items", [])
            ]
            log.pdata["checkin_lists"] = [
                checkin_list_cache.get(i["id"], "?")
                for i in log.pdata.get("checkin_lists", [])
                if i["id"] in checkin_list_cache
            ]
            if log.pdata.get("subevent"):
                try:
                    log.pdata["subevent_obj"] = self.request.event.subevents.get(
                        pk=log.pdata["subevent"]["id"]
                    )
                except SubEvent.DoesNotExist:
                    pass

        return ctx


class ReminderView(EventPermissionRequiredMixin, FormView):
    template_name = "pretix_juvare_notify/reminders.html"
    permission = "can_change_orders"
    form_class = JuvareReminderSettingsForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["obj"] = self.request.event
        return kwargs

    def form_valid(self, form):
        form.save()
        messages.success(self.request, _("Settings have been updated."))

        return redirect(
            "plugins:pretix_juvare_notify:reminders",
            event=self.request.event.slug,
            organizer=self.request.event.organizer.slug,
        )

    def get_context_data(self, *args, **kwargs):
        ctx = super().get_context_data(*args, **kwargs)
        ctx["sent_reminders"] = SubEventReminder.objects.filter(
            subevent__event=self.request.event
        ).order_by("-updated")
        ctx["has_client_secret"] = bool(
            self.request.organizer.settings.juvare_client_secret
        )
        return ctx
