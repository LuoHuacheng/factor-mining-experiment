import logging
from app.core.logger import setup_logger


def test_setup_logger_root_name():
    logger = setup_logger("INFO")
    assert logger.name == "app"
    assert logger.level == logging.INFO


def test_no_qihuo_logger_created():
    manager = logging.Logger.manager
    for name in manager.loggerDict:
        assert not name.startswith("qihuo"), f"发现旧 logger 命名: {name}"
