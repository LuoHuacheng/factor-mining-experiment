from contextlib import ExitStack
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
from app.services.okx_quote_service import OkxQuoteService


@pytest.mark.asyncio
async def test_quote_services_initialization_dual():
    fake_redis = MagicMock()
    live_svc = OkxQuoteService(fake_redis, mode="live", source="okx")
    virtual_svc = OkxQuoteService(fake_redis, mode="virtual", source="okx_demo")

    assert live_svc._mode == "live"
    assert live_svc._source == "okx"
    assert virtual_svc._mode == "virtual"
    assert virtual_svc._source == "okx_demo"


@pytest.mark.asyncio
async def test_lifespan_dual_quote_lifecycle():
    from app.main import lifespan

    app = FastAPI()
    patches = [
        patch("app.main.load_settings"),
        patch("app.main.setup_logger"),
        patch("app.main.create_database_engine"),
        patch("app.main.create_session_factory"),
        patch("app.main.create_redis_connection", new_callable=AsyncMock),
        patch("app.main._init_tables", new_callable=AsyncMock),
        patch("app.connectors.okx.instruments.refresh_instruments", new_callable=AsyncMock),
        patch("app.data.instruments.all_instruments", return_value=[MagicMock(symbol="BTC-USDT-SWAP")]),
        patch("app.main.set_session_factory"),
        patch("app.main.start_scheduler", new_callable=AsyncMock),
        patch("app.main.start_notify_subscriber", new_callable=AsyncMock),
        patch("app.main.start_big_order_subscriber", new_callable=AsyncMock),
        patch("app.main.start_ops_alert_subscriber", new_callable=AsyncMock),
        patch("app.main.stop_ops_alert_subscriber", new_callable=AsyncMock),
        patch("app.main.stop_big_order_subscriber", new_callable=AsyncMock),
        patch("app.main.stop_notify_subscriber", new_callable=AsyncMock),
        patch("app.main.stop_scheduler", new_callable=AsyncMock),
        patch("app.main.close_redis_connection", new_callable=AsyncMock),
        patch("app.services.okx_quote_service.OkxQuoteService"),
        patch("app.connectors.okx.client.OkxRestClient"),
    ]

    with ExitStack() as stack:
        mocks = [stack.enter_context(p) for p in patches]
        mock_engine = mocks[2]
        mock_svc_cls = mocks[18]
        mock_client_cls = mocks[19]

        mock_engine.return_value.dispose = AsyncMock()
        live_svc = MagicMock()
        live_svc.start = AsyncMock()
        live_svc.stop = AsyncMock()
        virtual_svc = MagicMock()
        virtual_svc.start = AsyncMock()
        virtual_svc.stop = AsyncMock()
        mock_svc_cls.side_effect = [live_svc, virtual_svc]

        live_client = MagicMock()
        live_client.aclose = AsyncMock()
        demo_client = MagicMock()
        demo_client.aclose = AsyncMock()
        mock_client_cls.side_effect = [live_client, demo_client]

        async with lifespan(app):
            assert app.state.okx_client == live_client
            assert app.state.okx_demo_client == demo_client
            assert app.state.okx_quotes == live_svc
            assert app.state.okx_quotes_live == live_svc
            assert app.state.okx_quotes_virtual == virtual_svc
            live_svc.start.assert_awaited_once_with(["BTC-USDT-SWAP"])
            virtual_svc.start.assert_awaited_once_with(["BTC-USDT-SWAP"])

        live_svc.stop.assert_awaited_once()
        virtual_svc.stop.assert_awaited_once()
        live_client.aclose.assert_awaited_once()
        demo_client.aclose.assert_awaited_once()
