import logging
import json
from dataclasses import dataclass
from fastapi import Request
from enum import Enum
from datetime import datetime, timezone

# Configura un logger específico para auditoría
audit_log = logging.getLogger("audit")

if not audit_log.handlers:
    audit_log.addHandler(logging.StreamHandler())
    audit_log.setLevel(logging.INFO)


class AuditEvent(str, Enum):
    # Existentes
    USER_LOGIN_SUCCESS = "USER_LOGIN_SUCCESS"
    USER_LOGIN_FAILED = "USER_LOGIN_FAILED"
    USER_REGISTERED = "USER_REGISTERED"
    ORDER_CREATED = "ORDER_CREATED"
    ORDER_STATUS_CHANGED = "ORDER_STATUS_CHANGED"
    PAYMENT_WEBHOOK_RECEIVED = "PAYMENT_WEBHOOK_RECEIVED"
    # Nuevos — auth
    PASSWORD_RESET_REQUESTED = "PASSWORD_RESET_REQUESTED"
    PASSWORD_RESET_COMPLETED = "PASSWORD_RESET_COMPLETED"
    # Nuevos — admin
    ADMIN_ROLE_CHANGED = "ADMIN_ROLE_CHANGED"
    ADMIN_USER_DELETED = "ADMIN_USER_DELETED"
    ADMIN_PRODUCT_CREATED = "ADMIN_PRODUCT_CREATED"
    ADMIN_PRODUCT_UPDATED = "ADMIN_PRODUCT_UPDATED"
    # Nuevos — payments / orders / inventory
    PAYMENT_FAILED = "PAYMENT_FAILED"
    MP_PREFERENCE_CREATED = "MP_PREFERENCE_CREATED"
    SIGNATURE_INVALID = "SIGNATURE_INVALID"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    STOCK_DECREMENTED = "STOCK_DECREMENTED"
    STOCK_RESTORED = "STOCK_RESTORED"


@dataclass(frozen=True)
class AuditContext:
    """Contexto de auditoría transportado del router al service layer."""
    client_ip: str = "N/A"
    method: str = "N/A"
    path: str = "N/A"

    @classmethod
    def from_request(cls, request: Request) -> "AuditContext":
        client_ip = "N/A"
        if request.client:
            client_ip = request.client.host
        return cls(
            client_ip=client_ip,
            method=request.method,
            path=request.url.path,
        )


async def _emit(event: AuditEvent, ctx: AuditContext, details: dict) -> None:
    """Emite un evento de auditoría como JSON. Nunca levanta excepciones."""
    try:
        log_data = {
            "event": event.value,
            "client_ip": ctx.client_ip,
            "method": ctx.method,
            "path": ctx.path,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "details": details,
        }
        audit_log.info(json.dumps(log_data, ensure_ascii=False))
    except Exception as exc:
        logging.getLogger(__name__).warning("Audit emit failed: %s", exc)


async def log_audit(
    event: AuditEvent, request: Request | None, details: dict
) -> None:
    """Registra un evento de auditoría desde un router (con Request)."""
    ctx = AuditContext.from_request(request) if request else AuditContext()
    await _emit(event, ctx, details)


async def log_audit_ctx(
    event: AuditEvent, *, ctx: AuditContext | None, details: dict
) -> None:
    """Registra un evento de auditoría desde el service layer (sin Request)."""
    await _emit(event, ctx or AuditContext(), details)
