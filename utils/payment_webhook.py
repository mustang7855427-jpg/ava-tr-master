import hashlib
import hmac
import json
import os
import re
import time

import redis
from aiohttp import web

from utils.server_logging import payment_audit_logger


MAX_BODY_SIZE = 64 * 1024
MAX_TIMESTAMP_AGE_SECONDS = 300
IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
CURRENCY_RE = re.compile(r"[A-Z]{3}\Z")

STORE_PAYMENT_SCRIPT = """
if redis.call('EXISTS', KEYS[1]) == 1 then
    return 1
end
if redis.call('EXISTS', KEYS[2]) == 1 then
    return 2
end
redis.call('SET', KEYS[1], ARGV[1])
redis.call('SET', KEYS[2], ARGV[1])
return 0
"""


def _validate_payload(payload, merchant_id):
    if not isinstance(payload, dict):
        raise web.HTTPBadRequest(text="Oczekiwano obiektu JSON.")

    required = {
        "event_id",
        "event_type",
        "merchant_id",
        "payment_id",
        "payment_status",
        "order_id",
        "amount_minor",
        "currency",
    }
    if not required.issubset(payload):
        raise web.HTTPBadRequest(text="Brakuje wymaganych pól zdarzenia.")

    for field in ("event_id", "payment_id", "order_id"):
        value = payload[field]
        if not isinstance(value, str) or not IDENTIFIER_RE.fullmatch(value):
            raise web.HTTPBadRequest(text=f"Nieprawidłowe pole: {field}.")

    received_merchant_id = payload["merchant_id"]
    if (not isinstance(received_merchant_id, str)
            or not hmac.compare_digest(received_merchant_id, merchant_id)):
        raise web.HTTPForbidden(text="Zdarzenie dotyczy innego sprzedawcy.")

    if (payload["event_type"] != "payment.completed"
            or payload["payment_status"] != "COMPLETED"):
        raise web.HTTPBadRequest(
            text="Endpoint przyjmuje wyłącznie zakończone płatności.")

    amount = payload["amount_minor"]
    if (isinstance(amount, bool) or not isinstance(amount, int)
            or amount <= 0 or amount > 2**63 - 1):
        raise web.HTTPBadRequest(
            text="Kwota musi być dodatnią liczbą całkowitą w najmniejszych "
                 "jednostkach waluty.")

    currency = payload["currency"]
    if not isinstance(currency, str) or not CURRENCY_RE.fullmatch(currency):
        raise web.HTTPBadRequest(
            text="Waluta musi być kodem ISO 4217 zapisanym wielkimi literami.")


async def payment_webhook(request):
    secret = os.environ.get("TORTUNGA_PAYMENT_WEBHOOK_SECRET", "")
    merchant_id = os.environ.get("TORTUNGA_PAYMENT_MERCHANT_ID", "")
    if not secret or not merchant_id:
        raise web.HTTPServiceUnavailable(
            text="Webhook płatności nie jest skonfigurowany.")

    if request.content_type != "application/json":
        raise web.HTTPUnsupportedMediaType(
            text="Webhook wymaga Content-Type: application/json.")
    if (request.content_length is not None
            and request.content_length > MAX_BODY_SIZE):
        raise web.HTTPRequestEntityTooLarge(
            max_size=MAX_BODY_SIZE,
            actual_size=request.content_length,
        )

    timestamp = request.headers.get("X-Tortunga-Timestamp", "")
    signature = request.headers.get("X-Tortunga-Signature", "")
    if (not timestamp.isdecimal() or len(timestamp) > 12
            or not re.fullmatch(r"sha256=[0-9a-f]{64}", signature)):
        raise web.HTTPUnauthorized(text="Brak prawidłowego podpisu webhooka.")

    event_time = int(timestamp)
    if abs(int(time.time()) - event_time) > MAX_TIMESTAMP_AGE_SECONDS:
        raise web.HTTPUnauthorized(text="Podpis webhooka wygasł.")

    body = await request.read()
    if len(body) > MAX_BODY_SIZE:
        raise web.HTTPRequestEntityTooLarge(
            max_size=MAX_BODY_SIZE,
            actual_size=len(body),
        )

    signed_content = timestamp.encode("ascii") + b"." + body
    expected_signature = "sha256=" + hmac.new(
        secret.encode("utf-8"),
        signed_content,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        raise web.HTTPUnauthorized(text="Nieprawidłowy podpis webhooka.")

    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise web.HTTPBadRequest(text="Treść webhooka nie jest poprawnym JSON-em.") from error

    _validate_payload(payload, merchant_id)
    received = {
        "event_id": payload["event_id"],
        "event_type": payload["event_type"],
        "merchant_id": payload["merchant_id"],
        "payment_id": payload["payment_id"],
        "payment_status": payload["payment_status"],
        "order_id": payload["order_id"],
        "amount_minor": payload["amount_minor"],
        "currency": payload["currency"],
        "received_at": int(time.time()),
    }
    record = json.dumps(received, separators=(",", ":"), sort_keys=True)

    try:
        result = request.app["redis"].eval(
            STORE_PAYMENT_SCRIPT,
            2,
            f"payments:tortunga:event:{payload['event_id']}",
            f"payments:tortunga:payment:{payload['payment_id']}",
            record,
        )
    except redis.RedisError as error:
        request.app.logger.exception(
            "Nie udało się trwale zapisać zweryfikowanego zdarzenia płatności.")
        raise web.HTTPServiceUnavailable(
            text="Nie można teraz zapisać zdarzenia płatności.") from error

    if result == 1:
        payment_audit_logger().info(json.dumps({
            "status": "duplicate_event",
            "event_id": payload["event_id"],
            "payment_id": payload["payment_id"],
            "order_id": payload["order_id"],
            "amount_minor": payload["amount_minor"],
            "currency": payload["currency"],
            "received_at": int(time.time()),
        }, separators=(",", ":"), sort_keys=True))
        return web.json_response({"status": "already_recorded"})
    if result == 2:
        payment_audit_logger().warning(json.dumps({
            "status": "duplicate_payment_conflict",
            "event_id": payload["event_id"],
            "payment_id": payload["payment_id"],
            "order_id": payload["order_id"],
            "received_at": int(time.time()),
        }, separators=(",", ":"), sort_keys=True))
        raise web.HTTPConflict(
            text="Ta płatność została już zarejestrowana pod innym zdarzeniem.")

    payment_audit_logger().info(json.dumps({
        **received,
        "status": "recorded",
    }, separators=(",", ":"), sort_keys=True))
    request.app.logger.info(
        "Zapisano potwierdzenie płatności %s",
        payload["payment_id"],
    )
    return web.json_response({"status": "recorded"}, status=201)
