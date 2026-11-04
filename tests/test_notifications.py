import hashlib
import hmac
import json
import uuid
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest import mock

import requests
from django.conf import settings
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from apps.customers.models import Customer
from apps.notifications import services, tasks
from apps.notifications.models import Notification, WebhookEvent
from apps.orders import services as order_services
from apps.orders.models import Order
from tests.helpers import make_variant

WA = dict(
    WHATSAPP_ACCESS_TOKEN="tok_test",
    WHATSAPP_PHONE_NUMBER_ID="123456",
    WHATSAPP_API_VERSION="v99.0",
    OWNER_WHATSAPP_NUMBER="+254700000001",
    WHATSAPP_TEMPLATE_LANGUAGE="en",
    WHATSAPP_VERIFY_TOKEN="verify-me",
    WHATSAPP_APP_SECRET="app-secret",
    NOTIFICATION_MAX_ATTEMPTS=3,
    DELIVERY_FEE=Decimal("0.00"),
)
POST = "apps.notifications.whatsapp.requests.post"


def ok_response(message_id="wamid.TEST"):
    r = mock.Mock()
    r.status_code = 200
    r.json.return_value = {"messaging_product": "whatsapp", "messages": [{"id": message_id}]}
    return r


def error_response(status, code=100, message="boom"):
    r = mock.Mock()
    r.status_code = status
    r.json.return_value = {"error": {"message": message, "code": code}}
    return r


def place(consent=True, qty=2, milk=None, key=None):
    milk = milk or make_variant("80.00", 20)
    order, _ = order_services.place_order(
        items=[{"variant_id": milk.id, "quantity": qty}],
        name="Jane Wanjiku", phone="0712345678", whatsapp_consent=consent,
        delivery_area="Ndagani", delivery_address="Near the market",
        idempotency_key=key or uuid.uuid4().hex,
    )
    return order


def owner_note(order):
    return Notification.objects.get(order=order, recipient_type="OWNER")


def customer_note(order):
    return Notification.objects.get(order=order, recipient_type="CUSTOMER", event="ORDER_RECEIVED")


@override_settings(**WA)
class QueueTests(TestCase):
    def test_creates_owner_and_customer_rows(self):
        order = place()
        owner = owner_note(order)
        cust = customer_note(order)
        self.assertEqual((owner.event, owner.template_name), ("OWNER_NEW_ORDER", "rc_owner_new_order"))
        self.assertEqual(owner.params[0], order.reference)
        self.assertEqual(owner.params[1], "Jane Wanjiku")
        self.assertEqual(owner.params[2], "+254712345678")
        self.assertEqual(owner.params[3], "Ndagani")
        self.assertIn("2 x", owner.params[4])
        self.assertEqual(owner.params[5], "160")
        self.assertEqual(cust.template_name, "rc_order_received")
        self.assertEqual(cust.recipient_phone, "+254712345678")
        self.assertEqual(cust.params, ["Jane Wanjiku", order.reference, "160", "Ndagani"])
        self.assertEqual((owner.status, owner.attempts, cust.status, cust.attempts), ("PENDING", 0, "PENDING", 0))

    def test_no_consent_means_owner_row_only(self):
        order = place(consent=False)
        self.assertEqual(Notification.objects.filter(order=order).count(), 1)
        self.assertEqual(Notification.objects.get(order=order).recipient_type, "OWNER")

    def test_replayed_checkout_creates_no_duplicates(self):
        milk = make_variant("80.00", 20)
        place(milk=milk, key="same-key")
        place(milk=milk, key="same-key")
        self.assertEqual(Notification.objects.count(), 2)

    def test_notification_rows_roll_back_with_the_order(self):
        with mock.patch("apps.notifications.services._dispatch_on_commit", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                place()
        self.assertEqual(Notification.objects.count(), 0)
        self.assertEqual(Order.objects.count(), 0)

    def test_status_changes_queue_customer_messages(self):
        order = place()
        order_services.change_status(order.pk, "CONFIRMED")
        order_services.change_status(order.pk, "PREPARING")
        order_services.change_status(order.pk, "OUT_FOR_DELIVERY")
        events = list(
            Notification.objects.filter(order=order, recipient_type="CUSTOMER")
            .order_by("id").values_list("event", flat=True)
        )
        self.assertEqual(events, ["ORDER_RECEIVED", "ORDER_CONFIRMED", "ORDER_OUT_FOR_DELIVERY"])
        confirmed = Notification.objects.get(order=order, event="ORDER_CONFIRMED")
        self.assertEqual(confirmed.params, ["Jane Wanjiku", order.reference])
        self.assertEqual(confirmed.template_name, "rc_order_confirmed")

    def test_status_changes_without_consent_queue_nothing(self):
        order = place(consent=False)
        order_services.change_status(order.pk, "CONFIRMED")
        self.assertEqual(Notification.objects.filter(recipient_type="CUSTOMER").count(), 0)

    def test_cancelled_and_delivery_failed_events(self):
        order = place()
        for status in ["CONFIRMED", "PREPARING", "OUT_FOR_DELIVERY", "DELIVERY_FAILED"]:
            order_services.change_status(order.pk, status)
        order_services.change_status(order.pk, "CANCELLED", note="Customer unreachable")
        events = set(Notification.objects.filter(order=order).values_list("event", flat=True))
        self.assertIn("DELIVERY_FAILED", events)
        self.assertIn("ORDER_CANCELLED", events)

    def test_repeated_status_gets_its_own_notification(self):
        order = place()
        for status in ["CONFIRMED", "PREPARING", "OUT_FOR_DELIVERY", "DELIVERY_FAILED", "OUT_FOR_DELIVERY"]:
            order_services.change_status(order.pk, status)
        self.assertEqual(Notification.objects.filter(order=order, event="ORDER_OUT_FOR_DELIVERY").count(), 2)

    def test_parameter_cleaning(self):
        self.assertEqual(services._clean("a\n  b\t\tc"), "a b c")
        self.assertEqual(services._clean(""), "-")
        self.assertEqual(services._clean(None), "-")
        long = services._clean("x" * 500, 50)
        self.assertEqual(len(long), 50)
        self.assertTrue(long.endswith("..."))

    def test_money_formatting(self):
        self.assertEqual(services._money(Decimal("310.00")), "310")
        self.assertEqual(services._money(Decimal("310.50")), "310.50")

    def test_multiline_product_names_never_reach_template_params(self):
        milk = make_variant("80.00", 20, name="Fresh\n   Milk     1 litre")
        order = place(milk=milk)
        items = owner_note(order).params[4]
        self.assertNotIn("\n", items)
        self.assertNotIn("  ", items)


@override_settings(**WA)
class CommitDispatchTests(TestCase):
    def test_sends_owner_and_customer_after_commit(self):
        with mock.patch(POST, side_effect=[ok_response("wamid.A"), ok_response("wamid.B")]) as post:
            with self.captureOnCommitCallbacks(execute=True):
                order = place()
        owner = owner_note(order)
        cust = customer_note(order)
        self.assertEqual((owner.status, owner.message_id, owner.attempts), ("SENT", "wamid.A", 1))
        self.assertEqual((cust.status, cust.message_id, cust.attempts), ("SENT", "wamid.B", 1))
        self.assertEqual(post.call_count, 2)

        first = post.call_args_list[0]
        self.assertEqual(first.args[0], "https://graph.facebook.com/v99.0/123456/messages")
        self.assertEqual(first.kwargs["headers"]["Authorization"], "Bearer tok_test")
        self.assertEqual(first.kwargs["timeout"], settings.WHATSAPP_TIMEOUT)
        body = first.kwargs["json"]
        self.assertEqual(body["messaging_product"], "whatsapp")
        self.assertEqual(body["to"], "254700000001")
        self.assertEqual(body["type"], "template")
        self.assertEqual(body["template"]["name"], "rc_owner_new_order")
        self.assertEqual(body["template"]["language"]["code"], "en")
        component = body["template"]["components"][0]
        self.assertEqual(component["type"], "body")
        self.assertTrue(all(p["type"] == "text" for p in component["parameters"]))
        self.assertEqual(component["parameters"][0]["text"], order.reference)
        second_body = post.call_args_list[1].kwargs["json"]
        self.assertEqual(second_body["to"], "254712345678")
        self.assertEqual(second_body["template"]["name"], "rc_order_received")

    def test_order_is_saved_even_when_whatsapp_is_down(self):
        with mock.patch(POST, side_effect=requests.ConnectionError("down")):
            with self.captureOnCommitCallbacks(execute=True):
                order = place()
        self.assertTrue(Order.objects.filter(pk=order.pk).exists())
        rows = Notification.objects.filter(order=order)
        self.assertEqual(set(rows.values_list("status", flat=True)), {"PENDING"})
        self.assertEqual(set(rows.values_list("attempts", flat=True)), {1})

    @override_settings(WHATSAPP_ACCESS_TOKEN="")
    def test_unconfigured_leaves_notifications_pending_without_calling_meta(self):
        with mock.patch(POST) as post:
            with self.captureOnCommitCallbacks(execute=True):
                order = place()
        post.assert_not_called()
        rows = Notification.objects.filter(order=order)
        self.assertEqual(set(rows.values_list("status", flat=True)), {"PENDING"})
        self.assertEqual(set(rows.values_list("attempts", flat=True)), {0})


@override_settings(**WA)
class AttemptTests(TestCase):
    def note(self, recipient="OWNER", consent=True):
        order = place(consent=consent)
        if recipient == "OWNER":
            return owner_note(order)
        return customer_note(order)

    def test_success_records_message_id(self):
        n = self.note()
        with mock.patch(POST, return_value=ok_response("wamid.S")):
            self.assertEqual(tasks.attempt_send(n.pk), "sent")
        n.refresh_from_db()
        self.assertEqual((n.status, n.message_id, n.attempts), ("SENT", "wamid.S", 1))
        self.assertIsNotNone(n.sent_at)

    def test_server_error_retries_with_backoff(self):
        n = self.note()
        now = timezone.now()
        with mock.patch(POST, return_value=error_response(500, 131000, "boom")):
            self.assertEqual(tasks.attempt_send(n.pk, now=now), "retry")
        n.refresh_from_db()
        self.assertEqual((n.status, n.attempts), ("PENDING", 1))
        self.assertGreater(n.next_attempt_at, now)
        self.assertIn("boom", n.last_error)
        with mock.patch(POST) as post:
            self.assertEqual(tasks.attempt_send(n.pk, now=now), "not_due")
        post.assert_not_called()
        with mock.patch(POST, return_value=ok_response()):
            self.assertEqual(tasks.attempt_send(n.pk, now=now + timedelta(minutes=2)), "sent")

    def test_gives_up_after_max_attempts(self):
        n = self.note()
        t0 = timezone.now()
        with mock.patch(POST, return_value=error_response(503, 1, "down")):
            self.assertEqual(tasks.attempt_send(n.pk, now=t0), "retry")
            self.assertEqual(tasks.attempt_send(n.pk, now=t0 + timedelta(minutes=10)), "retry")
            self.assertEqual(tasks.attempt_send(n.pk, now=t0 + timedelta(minutes=30)), "gave_up")
        n.refresh_from_db()
        self.assertEqual((n.status, n.attempts), ("GAVE_UP", 3))
        with mock.patch(POST) as post:
            self.assertEqual(tasks.attempt_send(n.pk, now=t0 + timedelta(days=1)), "not_due")
        post.assert_not_called()

    def test_client_error_is_permanent(self):
        n = self.note()
        with mock.patch(POST, return_value=error_response(400, 131026, "Message undeliverable")):
            self.assertEqual(tasks.attempt_send(n.pk), "failed")
        n.refresh_from_db()
        self.assertEqual((n.status, n.attempts), ("FAILED", 1))
        self.assertIn("131026", n.last_error)

    def test_rate_limit_429_is_retriable(self):
        n = self.note()
        with mock.patch(POST, return_value=error_response(429, 130429, "rate")):
            self.assertEqual(tasks.attempt_send(n.pk), "retry")

    def test_timeout_and_connection_errors_are_retriable(self):
        for exc in [requests.Timeout("slow"), requests.ConnectionError("down")]:
            with self.subTest(exc=type(exc).__name__):
                n = self.note()
                with mock.patch(POST, side_effect=exc):
                    self.assertEqual(tasks.attempt_send(n.pk), "retry")
                n.refresh_from_db()
                self.assertEqual(n.status, "PENDING")
                self.assertIn(type(exc).__name__, n.last_error)

    def test_success_without_message_id_is_not_retried(self):
        n = self.note()
        r = mock.Mock()
        r.status_code = 200
        r.json.return_value = {"messages": []}
        with mock.patch(POST, return_value=r):
            self.assertEqual(tasks.attempt_send(n.pk), "failed")
        n.refresh_from_db()
        self.assertEqual(n.status, "FAILED")

    def test_unexpected_exception_is_contained_and_retried(self):
        n = self.note()
        with mock.patch(POST, side_effect=ValueError("weird")):
            self.assertEqual(tasks.attempt_send(n.pk), "retry")
        n.refresh_from_db()
        self.assertEqual((n.status, n.attempts), ("PENDING", 1))

    def test_second_attempt_does_not_resend(self):
        n = self.note()
        with mock.patch(POST, return_value=ok_response()) as post:
            self.assertEqual(tasks.attempt_send(n.pk), "sent")
            self.assertEqual(tasks.attempt_send(n.pk), "not_due")
        self.assertEqual(post.call_count, 1)

    def test_row_claimed_elsewhere_is_not_sent(self):
        n = self.note()
        Notification.objects.filter(pk=n.pk).update(status="SENDING")
        with mock.patch(POST) as post:
            self.assertEqual(tasks.attempt_send(n.pk), "not_due")
        post.assert_not_called()

    def test_consent_withdrawn_before_send_skips_customer_message(self):
        n = self.note("CUSTOMER")
        Customer.objects.all().update(whatsapp_opt_in=False)
        with mock.patch(POST) as post:
            self.assertEqual(tasks.attempt_send(n.pk), "skipped")
        post.assert_not_called()
        n.refresh_from_db()
        self.assertEqual(n.status, "SKIPPED")

    @override_settings(WHATSAPP_ACCESS_TOKEN="")
    def test_missing_token_is_not_configured(self):
        n = self.note()
        with mock.patch(POST) as post:
            self.assertEqual(tasks.attempt_send(n.pk), "not_configured")
        post.assert_not_called()
        n.refresh_from_db()
        self.assertEqual((n.status, n.attempts), ("PENDING", 0))

    @override_settings(WHATSAPP_API_VERSION="")
    def test_missing_api_version_is_not_configured(self):
        n = self.note()
        self.assertEqual(tasks.attempt_send(n.pk), "not_configured")

    @override_settings(OWNER_WHATSAPP_NUMBER="")
    def test_missing_owner_number_blocks_only_owner_message(self):
        order = place()
        with mock.patch(POST, return_value=ok_response()):
            self.assertEqual(tasks.attempt_send(owner_note(order).pk), "not_configured")
            self.assertEqual(tasks.attempt_send(customer_note(order).pk), "sent")

    def test_unknown_notification(self):
        self.assertEqual(tasks.attempt_send(999999), "missing")


@override_settings(**WA)
class OutboxTests(TestCase):
    def test_sends_all_due_notifications(self):
        order = place()
        with mock.patch(POST, side_effect=[ok_response("wamid.A"), ok_response("wamid.B")]):
            counts = tasks.process_outbox()
        self.assertEqual(counts["sent"], 2)
        self.assertEqual(set(Notification.objects.filter(order=order).values_list("status", flat=True)), {"SENT"})

    def test_second_run_sends_nothing_more(self):
        place()
        with mock.patch(POST, side_effect=[ok_response("wamid.A"), ok_response("wamid.B")]) as post:
            tasks.process_outbox()
            counts = tasks.process_outbox()
        self.assertEqual(post.call_count, 2)
        self.assertFalse(counts)

    def test_one_recipient_failing_does_not_block_the_other(self):
        order = place()
        with mock.patch(POST, side_effect=[error_response(500), ok_response("wamid.B")]):
            counts = tasks.process_outbox()
        self.assertEqual((counts["retry"], counts["sent"]), (1, 1))
        self.assertEqual(owner_note(order).status, "PENDING")
        self.assertEqual(customer_note(order).status, "SENT")

    def test_not_yet_due_rows_are_left_alone(self):
        order = place()
        Notification.objects.filter(order=order).update(next_attempt_at=timezone.now() + timedelta(hours=1))
        with mock.patch(POST) as post:
            counts = tasks.process_outbox()
        post.assert_not_called()
        self.assertFalse(counts)

    def test_batch_size_is_respected(self):
        place()
        with mock.patch(POST, return_value=ok_response()) as post:
            counts = tasks.process_outbox(batch_size=1)
        self.assertEqual(counts["sent"], 1)
        self.assertEqual(post.call_count, 1)

    def test_stale_claims_are_recovered_and_sent(self):
        order = place()
        Notification.objects.filter(order=order).update(
            status="SENDING", claimed_at=timezone.now() - timedelta(minutes=10), attempts=1
        )
        with mock.patch(POST, return_value=ok_response()):
            counts = tasks.process_outbox()
        self.assertEqual(counts["recovered"], 2)
        self.assertEqual(counts["sent"], 2)

    def test_fresh_claims_are_not_touched(self):
        order = place()
        Notification.objects.filter(order=order).update(status="SENDING", claimed_at=timezone.now())
        with mock.patch(POST) as post:
            tasks.process_outbox()
        post.assert_not_called()

    def test_requeue_resets_only_failed_and_gave_up(self):
        order = place()
        owner = owner_note(order)
        cust = customer_note(order)
        Notification.objects.filter(pk=owner.pk).update(status="FAILED", attempts=2, last_error="x")
        Notification.objects.filter(pk=cust.pk).update(status="SENT")
        self.assertEqual(services.requeue([owner.pk, cust.pk]), 1)
        owner.refresh_from_db()
        cust.refresh_from_db()
        self.assertEqual((owner.status, owner.attempts, owner.last_error), ("PENDING", 0, ""))
        self.assertEqual(cust.status, "SENT")

    def test_process_command_output(self):
        place()
        out = StringIO()
        with mock.patch(POST, side_effect=[ok_response("wamid.A"), ok_response("wamid.B")]):
            call_command("process_notifications", stdout=out)
        self.assertIn("sent=2", out.getvalue())

    def test_process_command_with_nothing_to_do(self):
        out = StringIO()
        call_command("process_notifications", stdout=out)
        self.assertIn("nothing to do", out.getvalue())

    def test_requeue_command(self):
        order = place()
        Notification.objects.filter(order=order).update(status="GAVE_UP")
        out = StringIO()
        call_command("requeue_notifications", "--failed", stdout=out)
        self.assertIn("Re-queued 2", out.getvalue())
        self.assertEqual(set(Notification.objects.values_list("status", flat=True)), {"PENDING"})


def status_payload(message_id, status, timestamp="1700000000", errors=None):
    item = {"id": message_id, "status": status, "timestamp": str(timestamp), "recipient_id": "254712345678"}
    if errors:
        item["errors"] = errors
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "WABA", "changes": [{"field": "messages", "value": {
            "messaging_product": "whatsapp", "metadata": {"phone_number_id": "123456"}, "statuses": [item],
        }}]}],
    }


@override_settings(**WA)
class WebhookTests(TestCase):
    url = "/webhooks/whatsapp/"

    def send(self, payload=None, secret="app-secret", header=None, raw=None, client=None):
        raw = raw if raw is not None else json.dumps(payload).encode()
        sig = header if header is not None else "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        extra = {"HTTP_X_HUB_SIGNATURE_256": sig} if sig else {}
        return (client or self.client).post(self.url, data=raw, content_type="application/json", **extra)

    def sent_note(self, message_id="wamid.X"):
        order = place()
        note = customer_note(order)
        Notification.objects.filter(pk=note.pk).update(status="SENT", message_id=message_id)
        return note

    def status_of(self, note):
        return Notification.objects.get(pk=note.pk).status

    # --- GET verification ---
    def test_verification_handshake(self):
        response = self.client.get(self.url, {"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "12345"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"12345")

    def test_verification_rejects_wrong_token_or_mode(self):
        bad = [
            {"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "1"},
            {"hub.mode": "unsubscribe", "hub.verify_token": "verify-me", "hub.challenge": "1"},
            {"hub.challenge": "1"},
        ]
        for params in bad:
            with self.subTest(params=params):
                self.assertEqual(self.client.get(self.url, params).status_code, 403)

    @override_settings(WHATSAPP_VERIFY_TOKEN="")
    def test_verification_refused_when_no_token_configured(self):
        response = self.client.get(self.url, {"hub.mode": "subscribe", "hub.verify_token": "", "hub.challenge": "1"})
        self.assertEqual(response.status_code, 403)

    def test_only_get_and_post_allowed(self):
        self.assertEqual(self.client.put(self.url).status_code, 405)

    # --- POST signature ---
    def test_invalid_signature_rejected(self):
        note = self.sent_note()
        payload = status_payload("wamid.X", "delivered")
        for kwargs in [{"secret": "wrong"}, {"header": ""}, {"header": "md5=abc"}, {"header": "sha256="}]:
            with self.subTest(kwargs=kwargs):
                self.assertEqual(self.send(payload, **kwargs).status_code, 403)
        self.assertEqual(self.status_of(note), "SENT")
        self.assertEqual(WebhookEvent.objects.count(), 0)

    @override_settings(WHATSAPP_APP_SECRET="")
    def test_unsigned_traffic_refused_when_no_secret_configured(self):
        self.assertEqual(self.send(status_payload("wamid.X", "delivered"), secret="").status_code, 503)

    def test_csrf_exempt_for_meta(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(self.send(status_payload("wamid.X", "sent"), client=client).status_code, 200)

    def test_malformed_payloads(self):
        self.assertEqual(self.send(raw=b"{not json").status_code, 400)
        self.assertEqual(self.send(raw=b"[1, 2]").status_code, 400)

    def test_oversized_body_rejected(self):
        self.assertEqual(self.send(raw=b"x" * 120_000).status_code, 413)

    # --- status handling ---
    def test_delivered_then_read(self):
        note = self.sent_note()
        self.assertEqual(self.send(status_payload("wamid.X", "delivered", 100)).status_code, 200)
        self.assertEqual(self.status_of(note), "DELIVERED")
        self.send(status_payload("wamid.X", "read", 200))
        self.assertEqual(self.status_of(note), "READ")
        self.assertTrue(all(WebhookEvent.objects.values_list("processed", flat=True)))

    def test_out_of_order_events_never_go_backwards(self):
        note = self.sent_note()
        self.send(status_payload("wamid.X", "read", 200))
        self.send(status_payload("wamid.X", "delivered", 100))
        self.send(status_payload("wamid.X", "sent", 50))
        self.assertEqual(self.status_of(note), "READ")

    def test_failed_status_records_error(self):
        note = self.sent_note()
        errors = [{"code": 131026, "title": "Message undeliverable"}]
        self.send(status_payload("wamid.X", "failed", errors=errors))
        n = Notification.objects.get(pk=note.pk)
        self.assertEqual(n.status, "FAILED")
        self.assertIn("131026", n.last_error)
        self.assertIn("undeliverable", n.last_error)

    def test_late_failed_does_not_override_delivery(self):
        note = self.sent_note()
        self.send(status_payload("wamid.X", "delivered", 100))
        self.send(status_payload("wamid.X", "failed", 150))
        self.assertEqual(self.status_of(note), "DELIVERED")

    def test_delivery_evidence_overrides_earlier_failed(self):
        note = self.sent_note()
        self.send(status_payload("wamid.X", "failed", 100))
        self.send(status_payload("wamid.X", "delivered", 200))
        self.assertEqual(self.status_of(note), "DELIVERED")

    def test_duplicate_events_are_idempotent(self):
        self.sent_note()
        payload = status_payload("wamid.X", "delivered", 100)
        self.send(payload)
        self.send(payload)
        self.assertEqual(WebhookEvent.objects.count(), 1)

    def test_junk_timestamp_does_not_crash(self):
        note = self.sent_note()
        self.assertEqual(self.send(status_payload("wamid.X", "delivered", "abc")).status_code, 200)
        self.assertEqual(self.status_of(note), "DELIVERED")

    def test_ignores_inbound_messages_and_unknown_statuses(self):
        payload = status_payload("wamid.X", "deleted")
        payload["entry"][0]["changes"][0]["value"]["messages"] = [{"from": "254712345678", "id": "wamid.IN", "type": "text"}]
        self.assertEqual(self.send(payload).status_code, 200)
        self.assertEqual(WebhookEvent.objects.count(), 0)

    def test_multiple_statuses_in_one_payload(self):
        a = self.sent_note("wamid.A")
        b = self.sent_note("wamid.B")
        payload = status_payload("wamid.A", "delivered", 100)
        payload["entry"][0]["changes"][0]["value"]["statuses"].append(
            {"id": "wamid.B", "status": "read", "timestamp": "101"}
        )
        self.send(payload)
        self.assertEqual(self.status_of(a), "DELIVERED")
        self.assertEqual(self.status_of(b), "READ")

    def test_event_before_message_id_is_saved_is_applied_later(self):
        order = place()
        note = customer_note(order)
        Notification.objects.filter(pk=note.pk).update(status="SENDING")
        self.send(status_payload("wamid.LATE", "delivered", 100))
        event = WebhookEvent.objects.get()
        self.assertFalse(event.processed)
        Notification.objects.filter(pk=note.pk).update(status="SENT", message_id="wamid.LATE")
        counts = tasks.process_outbox()
        self.assertEqual(counts["events_applied"], 1)
        event.refresh_from_db()
        self.assertTrue(event.processed)
        self.assertEqual(self.status_of(note), "DELIVERED")

    def test_old_unmatched_events_expire(self):
        self.send(status_payload("wamid.NOBODY", "delivered", 100))
        event = WebhookEvent.objects.get()
        WebhookEvent.objects.filter(pk=event.pk).update(created_at=timezone.now() - timedelta(days=2))
        tasks.process_outbox()
        event.refresh_from_db()
        self.assertTrue(event.processed)