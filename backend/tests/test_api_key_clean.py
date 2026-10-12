import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.api_key_svc import (
    generate_raw_key,
    hash_key,
    authenticate,
    _prefix_of,
    _KEY_PREFIX,
)
from app.models.api_key import ApiKey


def test_new_key_prefix():
    key = generate_raw_key()
    assert key.startswith("ak_")
    assert _prefix_of(key).startswith("ak_")


@pytest.mark.asyncio
async def test_authenticate_supports_legacy_and_new_keys():
    legacy_key = "legacy_mock_test_token_12345678"
    legacy_hash = hash_key(legacy_key)

    mock_record = MagicMock(spec=ApiKey)
    mock_record.key_hash = legacy_hash
    mock_record.is_active = True

    session = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = mock_record
    session.execute.return_value = exec_result

    auth_result = await authenticate(session, legacy_key)
    assert auth_result is not None
    assert mock_record.last_used_at is not None

    new_key = generate_raw_key()
    mock_record.key_hash = hash_key(new_key)
    auth_result_new = await authenticate(session, new_key)
    assert auth_result_new is not None
