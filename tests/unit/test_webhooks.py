import hmac
import hashlib
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi import HTTPException

from app.routers.webhooks import verify_signature, WEBHOOK_SECRET

pytestmark = pytest.mark.asyncio

async def test_verify_signature_valid():
    body = b'{"event":"session.status_run_started","session_id":"sess_123"}'
    signature = hmac.new(
        WEBHOOK_SECRET.encode("utf-8"),
        body,
        hashlib.sha256
    ).hexdigest()

    request = MagicMock()
    request.body = AsyncMock(return_value=body)

    # Should not raise an exception
    await verify_signature(request, x_webhook_signature=signature)

async def test_verify_signature_invalid():
    body = b'{"event":"session.status_run_started","session_id":"sess_123"}'
    invalid_signature = "invalid_signature_hash"

    request = MagicMock()
    request.body = AsyncMock(return_value=body)

    with pytest.raises(HTTPException) as exc_info:
        await verify_signature(request, x_webhook_signature=invalid_signature)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid signature"
