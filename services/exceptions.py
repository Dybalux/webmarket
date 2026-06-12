"""Domain exception hierarchy for the service layer.

Every exception carries:
  - status_code: int — HTTP status code hint for router translation.
  - code: str — Stable machine-readable identifier (e.g. "not_found").
  - detail: str — Human-readable error message in Spanish.

Service functions raise these exceptions; routers catch them and translate
to HTTPException with byte-identical status code and detail string.
"""

# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------


class ServiceError(Exception):
    """Base for all domain exceptions in the service layer.

    Not raised directly by services; subclassed for specific error categories.
    """

    def __init__(
        self,
        detail: str,
        *,
        status_code: int = 500,
        code: str = "internal_error",
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.detail = detail
        super().__init__(detail)


# ---------------------------------------------------------------------------
# 404 — Resource not found
# ---------------------------------------------------------------------------


class NotFoundError(ServiceError):
    """Requested resource does not exist in the database."""

    def __init__(self, detail: str = "Recurso no encontrado.") -> None:
        super().__init__(detail, status_code=404, code="not_found")


class ProductNotFoundError(NotFoundError):
    """Product not found by ID."""

    def __init__(self, detail: str = "Producto no encontrado.") -> None:
        super().__init__(detail)


class ComboNotFoundError(NotFoundError):
    """Combo not found by ID."""

    def __init__(self, detail: str = "Combo no encontrado.") -> None:
        super().__init__(detail)


class OrderNotFoundError(NotFoundError):
    """Order not found by ID."""

    def __init__(self, detail: str = "Pedido no encontrado.") -> None:
        super().__init__(detail)


class CartItemNotFoundError(NotFoundError):
    """Item not found in the user's cart."""

    def __init__(self, detail: str = "El producto no está en el carrito.") -> None:
        super().__init__(detail)


# ---------------------------------------------------------------------------
# 400 — Validation errors
# ---------------------------------------------------------------------------


class ValidationError(ServiceError):
    """Input validation failed (domain-level, distinct from Pydantic's)."""

    def __init__(
        self,
        detail: str = "Error de validación.",
        *,
        code: str = "validation_error",
    ) -> None:
        super().__init__(detail, status_code=400, code=code)


class InvalidObjectIdError(ValidationError):
    """The provided ID string is not a valid MongoDB ObjectId."""

    def __init__(self, detail: str = "ID inválido.") -> None:
        super().__init__(detail, code="invalid_object_id")


# ---------------------------------------------------------------------------
# 409 — Conflict / stock errors
# ---------------------------------------------------------------------------


class InsufficientStockError(ServiceError):
    """Product stock is too low to fulfill the requested quantity."""

    def __init__(self, detail: str = "Stock insuficiente.") -> None:
        super().__init__(detail, status_code=409, code="insufficient_stock")


class ConcurrentStockUpdateError(ServiceError):
    """Race condition detected during stock decrement ($gte guard failed)."""

    def __init__(
        self,
        detail: str = "Actualización concurrente detectada. Intente nuevamente.",
    ) -> None:
        super().__init__(detail, status_code=409, code="concurrent_stock_update")


class InvalidStateTransitionError(ServiceError):
    """Attempted an illegal order status transition."""

    def __init__(
        self,
        detail: str = "Transición de estado inválida.",
    ) -> None:
        super().__init__(detail, status_code=409, code="invalid_state_transition")


class ConflictError(ServiceError):
    """Generic conflict (duplicate, etc.)."""

    def __init__(self, detail: str = "Conflicto.") -> None:
        super().__init__(detail, status_code=409, code="conflict")


class DuplicateProductNameError(ConflictError):
    """A product with this name already exists."""

    def __init__(self, detail: str = "El nombre del producto ya existe.") -> None:
        super().__init__(detail)


# ---------------------------------------------------------------------------
# 400 — Business rule violations
# ---------------------------------------------------------------------------


class ComboInactiveError(ServiceError):
    """Combo is no longer active / available."""

    def __init__(self, detail: str = "El combo no está disponible.") -> None:
        super().__init__(detail, status_code=400, code="combo_inactive")


class EmptyCartError(ServiceError):
    """User's cart has no items when trying to create an order."""

    def __init__(self, detail: str = "Tu carrito está vacío.") -> None:
        super().__init__(detail, status_code=400, code="empty_cart")


# ---------------------------------------------------------------------------
# 403 — Authorization
# ---------------------------------------------------------------------------


class ForbiddenError(ServiceError):
    """User is authenticated but not authorized for this resource."""

    def __init__(self, detail: str = "Acceso denegado.") -> None:
        super().__init__(detail, status_code=403, code="forbidden")


# ---------------------------------------------------------------------------
# 400 — Shipping zone errors
# ---------------------------------------------------------------------------


class ShippingZoneError(ServiceError):
    """Base for shipping zone validation errors."""

    def __init__(
        self,
        detail: str = "Error de zona de envío.",
        *,
        code: str = "shipping_zone_error",
    ) -> None:
        super().__init__(detail, status_code=400, code=code)


class ShippingZoneInvalidError(ShippingZoneError):
    """The chosen shipping zone is not recognized."""

    def __init__(self, detail: str = "Zona de envío inválida.") -> None:
        super().__init__(detail, code="shipping_zone_invalid")


class ShippingZoneDisabledError(ShippingZoneError):
    """The chosen shipping zone is currently disabled."""

    def __init__(self, detail: str = "Zona de envío deshabilitada.") -> None:
        super().__init__(detail, code="shipping_zone_disabled")


# ---------------------------------------------------------------------------
# 500 — Internal errors
# ---------------------------------------------------------------------------


class InternalError(ServiceError):
    """Unexpected internal error (DB write failed, etc.)."""

    def __init__(self, detail: str = "Error interno.") -> None:
        super().__init__(detail, status_code=500, code="internal_error")
