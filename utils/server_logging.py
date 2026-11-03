import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs"
MAX_LOG_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 4
PAYMENT_LOG_BACKUP_COUNT = 12


def _log_uncaught_exception(exception_type, exception, traceback):
    if issubclass(exception_type, KeyboardInterrupt):
        sys.__excepthook__(exception_type, exception, traceback)
        return
    logging.getLogger("server").critical(
        "Nieobsłużony wyjątek procesu",
        exc_info=(exception_type, exception, traceback),
    )


def _log_uncaught_thread_exception(arguments):
    logging.getLogger("server").critical(
        "Nieobsłużony wyjątek wątku %s",
        arguments.thread.name if arguments.thread else "unknown",
        exc_info=(
            arguments.exc_type,
            arguments.exc_value,
            arguments.exc_traceback,
        ),
    )


def configure_server_logging(log_name):
    if Path(log_name).name != log_name:
        raise ValueError("Nazwa pliku logu musi być pojedynczą nazwą pliku.")

    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        handler.close()

    if os.environ.get("RENDER_DEPLOYMENT") == "true":
        handler = logging.StreamHandler()
    else:
        LOG_DIR.mkdir(exist_ok=True)
        handler = RotatingFileHandler(
            LOG_DIR / log_name,
            maxBytes=MAX_LOG_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )

    handler.setFormatter(logging.Formatter(
        "%(levelname)-8s [%(asctime)s]  %(message)s",
        datefmt="%H:%M:%S",
    ))
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)

    payment_logger = logging.getLogger("payments.audit")
    for payment_handler in payment_logger.handlers[:]:
        payment_logger.removeHandler(payment_handler)
        payment_handler.close()
    if os.environ.get("RENDER_DEPLOYMENT") == "true":
        payment_handler = logging.StreamHandler()
    else:
        payment_handler = RotatingFileHandler(
            LOG_DIR / "payments.log",
            maxBytes=MAX_LOG_BYTES,
            backupCount=PAYMENT_LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
    payment_handler.setFormatter(logging.Formatter("%(message)s"))
    payment_logger.addHandler(payment_handler)
    payment_logger.setLevel(logging.INFO)
    payment_logger.propagate = False

    logging.captureWarnings(True)
    sys.excepthook = _log_uncaught_exception
    threading.excepthook = _log_uncaught_thread_exception


def payment_audit_logger():
    return logging.getLogger("payments.audit")
