import logging
import json
from fastapi import Request
from enum import Enum
from datetime import datetime, timezone

# Configura un logger específico para auditoría
audit_log = logging.getLogger("audit")

if not audit_log.handlers:
    audit_log.addHandler(logging.StreamHandler())
    audit_log.setLevel(logging.INFO)

class AuditEvent(str, Enum):
    USER_LOGIN_SUCCESS = "USER_LOGIN_SUCCESS"
    USER_LOGIN_FAILED = "USER_LOGIN_FAILED"
    USER_REGISTERED = "USER_REGISTERED"
    ORDER_CREATED = "ORDER_CREATED"
    ORDER_STATUS_CHANGED = "ORDER_STATUS_CHANGED"
    PAYMENT_WEBHOOK_RECEIVED = "PAYMENT_WEBHOOK_RECEIVED"

def log_audit(event: AuditEvent, request: Request, details: dict):
    """
    Registra un evento de auditoría en formato JSON.
    """
    client_ip = "N/A"
    method = "N/A"
    path = "N/A"

    if request:
        if request.client:
            client_ip = request.client.host
        method = request.method
        path = request.url.path

    log_data = {
        "event": event.value,
        "client_ip": client_ip,
        "method": method,
        "path": path,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "details": details
    }

    audit_log.info(json.dumps(log_data, ensure_ascii=False))
