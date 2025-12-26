from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import Response
from bson import ObjectId
import mercadopago
import logging

from models import Order, OrderStatus, TokenData
from database import get_database, get_collection
from security import get_current_active_user_id
from config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

# Configura el SDK de Mercado Pago al iniciar
sdk = mercadopago.SDK(settings.MERCADOPAGO_ACCESS_TOKEN)

# Colecciones de MongoDB
def get_orders_collection(db=Depends(get_database)):
    return get_collection("orders")
def get_payments_collection(db=Depends(get_database)):
    return get_collection("payments")

@router.post("/create-preference/{order_id}", response_model=dict)
async def create_payment_preference(
    order_id: str,
    user_id: str = Depends(get_current_active_user_id),
    orders_collection = Depends(get_orders_collection)
):
    """
    Crea una preferencia de pago en Mercado Pago para un pedido existente.
    Devuelve la URL de checkout a la que el frontend debe redirigir al usuario.
    """
    if not ObjectId.is_valid(order_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ID de pedido inválido.")

    # 1. Buscar el pedido y verificar que pertenece al usuario
    order = await orders_collection.find_one({"_id": ObjectId(order_id)})
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pedido no encontrado.")
    if order["user_id"] != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Este pedido no te pertenece.")
    if order["status"] != OrderStatus.PENDING.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Este pedido ya ha sido procesado o cancelado.")

    # 2. Formatear los ítems para la API de Mercado Pago
    items_for_mp = []
    for item in order["items"]:
        items_for_mp.append({
            "title": item["name"],
            "quantity": item["quantity"],
            "unit_price": item["price_at_purchase"],
            "currency_id": "ARS" # O la moneda correspondiente (CLP, MXN, etc.)
        })

    # 3. Crear la preferencia de pago
    preference_data = {
        "items": items_for_mp,
        "external_reference": order_id, # MUY IMPORTANTE: vincula el pago a nuestro pedido
        "back_urls": {
            "success": f"{settings.FRONTEND_URL}/payment/success?order_id={order_id}", # URL del frontend
            "failure": f"{settings.FRONTEND_URL}/payment/failure?order_id={order_id}",
            "pending": f"{settings.FRONTEND_URL}/payment/pending?order_id={order_id}"
        },
        # NOTA: notification_url se configura desde el panel de Mercado Pago
        # porque en la creación de preferencia está dando error de formato
        "auto_return": "approved",
    }
    
    try:
        preference_response = sdk.preference().create(preference_data)
        
        # Log completo de la respuesta para debugging
        logger.info(f"Respuesta completa de Mercado Pago: {preference_response}")
        
        # Verificar si la respuesta tiene el formato esperado
        if "response" not in preference_response:
            logger.error(f"Respuesta de MP sin 'response': {preference_response}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
                detail=f"Respuesta inesperada de Mercado Pago: {preference_response.get('message', 'Error desconocido')}"
            )
        
        preference = preference_response["response"]
        
        # Verificar que tenga los campos necesarios
        if "id" not in preference or "init_point" not in preference:
            logger.error(f"Preferencia sin campos requeridos: {preference}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="La preferencia de Mercado Pago no contiene los campos necesarios"
            )
        
        # Guardar el ID de preferencia en el pedido
        await orders_collection.update_one(
            {"_id": ObjectId(order_id)},
            {"$set": {"payment_preference_id": preference["id"]}}
        )
        
        logger.info(f"Preferencia de pago {preference['id']} creada para el pedido {order_id}.")
        return {"preference_id": preference["id"], "init_point": preference["init_point"]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error al crear preferencia de Mercado Pago: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail=f"Error al comunicarse con Mercado Pago: {str(e)}"
        )

@router.post("/webhook")
async def handle_mercadopago_webhook(
    request: Request,
    orders_collection = Depends(get_orders_collection),
    payments_collection = Depends(get_payments_collection)
):
    """
    Endpoint para recibir notificaciones (webhooks) de Mercado Pago.
    Este endpoint debe ser público.
    """
    query_params = request.query_params
    logger.info(f"Webhook de Mercado Pago recibido: {query_params}")
    
    topic = query_params.get("topic")
    payment_id = query_params.get("id")
    
    if topic == "payment" and payment_id:
        try:
            # Obtener la información completa del pago desde Mercado Pago
            payment_info = sdk.payment().get(payment_id)["response"]
            
            # Guardar el evento de pago completo para auditoría
            await payments_collection.insert_one(payment_info)
            
            order_id = payment_info.get("external_reference")
            payment_status = payment_info.get("status")

            if not order_id:
                logger.warning(f"Webhook para pago {payment_id} recibido sin external_reference.")
                return Response(status_code=status.HTTP_200_OK)

            # Actualizar el estado del pedido en nuestra base de datos
            order = await orders_collection.find_one({"_id": ObjectId(order_id)})
            if order:
                if payment_status == "approved" and order["status"] == OrderStatus.PENDING.value:
                    await orders_collection.update_one(
                        {"_id": ObjectId(order_id)},
                        {"$set": {"status": OrderStatus.PROCESSING.value, "payment_id": payment_id}}
                    )
                    logger.info(f"Pedido {order_id} actualizado a 'En Proceso' por pago aprobado.")
                elif payment_status in ["rejected", "cancelled"]:
                    await orders_collection.update_one(
                        {"_id": ObjectId(order_id)},
                        {"$set": {"status": OrderStatus.CANCELLED.value, "payment_id": payment_id}}
                    )
                    logger.info(f"Pedido {order_id} actualizado a 'Cancelado' por pago rechazado/cancelado.")
            else:
                logger.warning(f"Pedido con ID {order_id} no encontrado para actualizar desde webhook.")

        except Exception as e:
            logger.error(f"Error procesando webhook de Mercado Pago: {e}", exc_info=True)
            # Devolvemos 200 para que MP no siga reintentando un webhook que falla por nuestra lógica interna
            return Response(status_code=status.HTTP_200_OK)

    return Response(status_code=status.HTTP_200_OK)