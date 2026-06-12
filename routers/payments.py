from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from bson import ObjectId
import logging

from database import get_database
from security import get_current_active_user_id
from services.payments import create_mp_preference, process_webhook
from services.exceptions import (
    ForbiddenError,
    InvalidStateTransitionError,
    NotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/create-preference/{order_id}", response_model=dict)
async def create_payment_preference(
    order_id: str,
    user_id: str = Depends(get_current_active_user_id),
    db=Depends(get_database),
):
    """Create a Mercado Pago preference for a PENDING order."""
    if not ObjectId.is_valid(order_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ID de pedido inválido.",
        )

    try:
        return await create_mp_preference(db, user_id, order_id)
    except NotFoundError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except ForbiddenError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except InvalidStateTransitionError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@router.post("/webhook")
async def handle_mercadopago_webhook(
    request: Request,
    db=Depends(get_database),
):
    """Receive Mercado Pago IPN webhook notifications.

    Idempotent — the same payment_id can be processed multiple times safely.
    """
    query_params = request.query_params
    logger.info("Webhook received: %s", query_params)

    topic = query_params.get("topic")
    payment_id = query_params.get("id")
    x_signature = request.headers.get("x-signature")
    x_request_id = request.headers.get("x-request-id")

    logger.info("Headers: x-signature=%s x-request-id=%s", x_signature, x_request_id)

    await process_webhook(db, topic, payment_id, x_signature, x_request_id)

    return Response(status_code=status.HTTP_200_OK)
