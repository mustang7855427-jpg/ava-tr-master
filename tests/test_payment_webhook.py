import hashlib
import hmac
import json
import logging
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import redis
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import utils.server_logging as server_logging
from utils.payment_webhook import payment_webhook


class FakeRedis:
    def __init__(self):
        self.records = {}

    def eval(self, _script, _key_count, event_key, payment_key, record):
        if event_key in self.records:
            return 1
        if payment_key in self.records:
            return 2
        self.records[event_key] = record
        self.records[payment_key] = record
        return 0


class FailingRedis:
    def eval(self, *_args):
        raise redis.RedisError("simulated Redis outage")


class PaymentWebhookTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.original_log_dir = server_logging.LOG_DIR
        self.addCleanup(self._restore_log_dir)
        server_logging.LOG_DIR = Path(self.temp_dir.name)

        self.environment = patch.dict(os.environ, {
            "RENDER_DEPLOYMENT": "",
            "TORTUNGA_PAYMENT_WEBHOOK_SECRET": "test-webhook-secret",
            "TORTUNGA_PAYMENT_MERCHANT_ID": "merchant-test",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

        self.previous_root_handlers = logging.getLogger().handlers[:]
        self.addCleanup(self._restore_root_handlers)
        self.previous_payment_handlers = logging.getLogger(
            "payments.audit"
        ).handlers[:]
        self.addCleanup(self._restore_payment_handlers)
        server_logging.configure_server_logging("test-web.log")

        self.redis = FakeRedis()
        self.app = web.Application(client_max_size=64 * 1024)
        self.app["redis"] = self.redis
        self.app.router.add_post("/webhooks/payments", payment_webhook)
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    def _restore_log_dir(self):
        server_logging.LOG_DIR = self.original_log_dir

    def _restore_root_handlers(self):
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
            handler.close()
        for handler in self.previous_root_handlers:
            root_logger.addHandler(handler)

    def _restore_payment_handlers(self):
        logger = logging.getLogger("payments.audit")
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()
        for handler in self.previous_payment_handlers:
            logger.addHandler(handler)

    @staticmethod
    def _event(event_id="evt-1", payment_id="pay-1"):
        return {
            "event_id": event_id,
            "event_type": "payment.completed",
            "merchant_id": "merchant-test",
            "payment_id": payment_id,
            "payment_status": "COMPLETED",
            "order_id": "order-1",
            "amount_minor": 1599,
            "currency": "EUR",
        }

    @staticmethod
    def _signed_request(payload, timestamp=None):
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        timestamp = str(int(time.time()) if timestamp is None else timestamp)
        signature = hmac.new(
            b"test-webhook-secret",
            timestamp.encode("ascii") + b"." + body,
            hashlib.sha256,
        ).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "X-Tortunga-Timestamp": timestamp,
            "X-Tortunga-Signature": f"sha256={signature}",
        }
        return body, headers

    def _audit_records(self):
        path = Path(self.temp_dir.name) / "payments.log"
        for handler in logging.getLogger("payments.audit").handlers:
            handler.flush()
        if not path.exists():
            return []
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
        ]

    async def test_valid_event_is_persisted_and_audited_without_raw_payload(self):
        payload = self._event()
        payload["untrusted_extra"] = "BODY_SENTINEL"
        payload["card_number"] = "4111111111111111"
        body, headers = self._signed_request(payload)

        response = await self.client.post(
            "/webhooks/payments", data=body, headers=headers
        )

        self.assertEqual(response.status, 201)
        self.assertEqual(await response.json(), {"status": "recorded"})
        stored = json.loads(self.redis.records[
            "payments:tortunga:event:evt-1"
        ])
        self.assertNotIn("card_number", stored)
        self.assertNotIn("untrusted_extra", stored)
        records = self._audit_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["status"], "recorded")
        self.assertEqual(records[0]["amount_minor"], 1599)
        self.assertEqual(records[0]["currency"], "EUR")
        log_text = (Path(self.temp_dir.name) / "payments.log").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("BODY_SENTINEL", log_text)
        self.assertNotIn("4111111111111111", log_text)
        self.assertNotIn("test-webhook-secret", log_text)

    async def test_repeated_event_is_idempotent_and_logged(self):
        body, headers = self._signed_request(self._event())

        first = await self.client.post(
            "/webhooks/payments", data=body, headers=headers
        )
        repeated = await self.client.post(
            "/webhooks/payments", data=body, headers=headers
        )

        self.assertEqual(first.status, 201)
        self.assertEqual(repeated.status, 200)
        self.assertEqual(await repeated.json(), {"status": "already_recorded"})
        self.assertEqual(
            [record["status"] for record in self._audit_records()],
            ["recorded", "duplicate_event"],
        )

    async def test_payment_id_cannot_be_reused_for_another_event(self):
        first_body, first_headers = self._signed_request(self._event())
        second_body, second_headers = self._signed_request(
            self._event(event_id="evt-2")
        )

        first = await self.client.post(
            "/webhooks/payments", data=first_body, headers=first_headers
        )
        conflict = await self.client.post(
            "/webhooks/payments", data=second_body, headers=second_headers
        )

        self.assertEqual(first.status, 201)
        self.assertEqual(conflict.status, 409)
        self.assertEqual(
            [record["status"] for record in self._audit_records()],
            ["recorded", "duplicate_payment_conflict"],
        )

    async def test_invalid_or_expired_signature_is_rejected_without_audit(self):
        body, headers = self._signed_request(self._event())
        headers["X-Tortunga-Signature"] = "sha256=" + "0" * 64
        invalid = await self.client.post(
            "/webhooks/payments", data=body, headers=headers
        )

        old_body, old_headers = self._signed_request(
            self._event(event_id="evt-old", payment_id="pay-old"),
            timestamp=int(time.time()) - 301,
        )
        expired = await self.client.post(
            "/webhooks/payments", data=old_body, headers=old_headers
        )

        self.assertEqual(invalid.status, 401)
        self.assertEqual(expired.status, 401)
        self.assertEqual(self._audit_records(), [])

    async def test_missing_configuration_and_redis_failure_return_errors(self):
        with patch.dict(os.environ, {"TORTUNGA_PAYMENT_WEBHOOK_SECRET": ""}):
            body, headers = self._signed_request(self._event())
            unavailable = await self.client.post(
                "/webhooks/payments", data=body, headers=headers
            )
        self.assertEqual(unavailable.status, 503)

        self.app["redis"] = FailingRedis()
        body, headers = self._signed_request(self._event())
        redis_error = await self.client.post(
            "/webhooks/payments", data=body, headers=headers
        )
        self.assertEqual(redis_error.status, 503)
        self.assertEqual(self._audit_records(), [])

    async def test_invalid_payload_is_rejected_without_audit(self):
        payload = self._event()
        payload["amount_minor"] = True
        body, headers = self._signed_request(payload)

        response = await self.client.post(
            "/webhooks/payments", data=body, headers=headers
        )

        self.assertEqual(response.status, 400)
        self.assertEqual(self._audit_records(), [])


if __name__ == "__main__":
    unittest.main()
