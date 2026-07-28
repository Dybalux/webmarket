"""
Servicio de email usando Resend para notificar a admins sobre nuevas órdenes.
"""
import html
from decimal import Decimal
import resend
from config import settings
from utils.money import quantize_money
import logging

logger = logging.getLogger(__name__)


async def send_new_order_notification(order_id: str, user_email: str, total_amount: Decimal, payment_method: str):
    """
    Envía un email a TODOS los admins notificando sobre una nueva orden usando Resend.
    
    Args:
        order_id: ID de la orden creada
        user_email: Email del usuario que hizo la orden
        total_amount: Monto total de la orden (Decimal)
        payment_method: Método de pago seleccionado
    """
    # Coerce to Decimal if needed (transition window: callers may pass float)
    if not isinstance(total_amount, Decimal):
        total_amount = Decimal(str(total_amount))
    # Si el email no está habilitado, solo loguear
    if not settings.EMAIL_ENABLED:
        logger.info(f"📧 Email deshabilitado. Nueva orden #{order_id} - ${total_amount} - {payment_method}")
        return
    
    # Validar configuración de Resend
    if not settings.RESEND_API_KEY:
        logger.warning("⚠️ RESEND_API_KEY no configurada. No se puede enviar notificación.")
        return
    
    if not settings.RESEND_FROM_EMAIL:
        logger.warning("⚠️ RESEND_FROM_EMAIL no configurado. No se puede enviar notificación.")
        return
    
    try:
        # Obtener todos los usuarios con rol admin
        from database import get_collection
        users_collection = get_collection("users")
        admin_users = await users_collection.find({"role": "admin"}).to_list(length=100)
        
        if not admin_users:
            logger.warning("⚠️ No hay usuarios admin en el sistema. No se enviarán emails.")
            return
        
        admin_emails = [user.get("email") for user in admin_users if user.get("email")]
        
        if not admin_emails:
            logger.warning("⚠️ Los usuarios admin no tienen emails configurados.")
            return
        
        logger.info(f"📧 Enviando notificación a {len(admin_emails)} admin(s): {', '.join(admin_emails)}")

        # Escape user-provided values to prevent XSS in HTML emails
        safe_order_id = html.escape(str(order_id))
        safe_user_email = html.escape(str(user_email))
        safe_total_amount = html.escape(str(quantize_money(total_amount)))
        safe_payment_method = html.escape(str(payment_method))

        # Crear el contenido HTML del email
        html_content = f"""
        <!DOCTYPE html>
        <html>
            <head>
                <meta charset="utf-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
            </head>
            <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; background-color: #f5f5f5;">
                <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; text-align: center;">
                    <h1 style="color: white; margin: 0; font-size: 24px;">🛒 Nueva Orden Recibida</h1>
                </div>

                <div style="padding: 30px; background: #f9f9f9;">
                    <div style="background: white; padding: 25px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                        <h2 style="color: #333; margin-top: 0; font-size: 20px;">Detalles de la Orden</h2>

                        <table style="width: 100%; border-collapse: collapse;">
                            <tr>
                                <td style="padding: 12px 0; border-bottom: 1px solid #eee;"><strong>Orden:</strong></td>
                                <td style="padding: 12px 0; border-bottom: 1px solid #eee; text-align: right;">#{safe_order_id}</td>
                            </tr>
                            <tr>
                                <td style="padding: 12px 0; border-bottom: 1px solid #eee;"><strong>Cliente:</strong></td>
                                <td style="padding: 12px 0; border-bottom: 1px solid #eee; text-align: right;">{safe_user_email}</td>
                            </tr>
                            <tr>
                                <td style="padding: 12px 0; border-bottom: 1px solid #eee;"><strong>Total:</strong></td>
                                <td style="padding: 12px 0; border-bottom: 1px solid #eee; text-align: right; color: #4CAF50; font-size: 18px; font-weight: bold;">${safe_total_amount}</td>
                            </tr>
                            <tr>
                                <td style="padding: 12px 0;"><strong>Método de Pago:</strong></td>
                                <td style="padding: 12px 0; text-align: right;">{safe_payment_method}</td>
                            </tr>
                        </table>

                        <div style="margin-top: 25px; padding: 15px; background: {'#fff3cd' if payment_method == 'Transferencia Bancaria' else '#d4edda'}; border-radius: 5px; border-left: 4px solid {'#ffc107' if payment_method == 'Transferencia Bancaria' else '#28a745'};">
                            <p style="margin: 0; color: #333;">
                                {'⚠️ <strong>Requiere confirmación manual de pago por transferencia</strong>' if payment_method == 'Transferencia Bancaria' else '✅ <strong>Pago procesado automáticamente por Mercado Pago</strong>'}
                            </p>
                        </div>
                    </div>
                </div>

                <div style="padding: 20px; text-align: center; color: #666; font-size: 12px;">
                    <p style="margin: 5px 0;">EscabiAPI - Sistema de Notificaciones</p>
                    <p style="margin: 5px 0;">Este es un email automático, por favor no responder.</p>
                </div>
            </body>
        </html>
        """
        
        # Configurar Resend con el API Key
        resend.api_key = settings.RESEND_API_KEY
        
        # Enviar el email usando Resend
        params = {
            "from": f"EscabiAPI <{settings.RESEND_FROM_EMAIL}>",
            "to": admin_emails,
            "subject": f"🛒 Nueva Orden #{order_id} - {payment_method}",
            "html": html_content,
        }
        
        response = resend.Emails.send(params)
        
        logger.info(f"✅ Email enviado exitosamente a {len(admin_emails)} admin(s): Nueva orden #{order_id}")
        logger.debug(f"Resend response: {response}")
        
    except Exception as e:
        # No romper la aplicación si falla el email
        logger.error(f"❌ Error al enviar email de notificación: {e}", exc_info=True)


async def send_password_reset_email(to_email: str, reset_url: str):
    """
    Sends a password-reset email via Resend following the existing pattern.

    Args:
        to_email: recipient email address
        reset_url: full URL the user clicks to reset (contains the token)
    """
    if not settings.EMAIL_ENABLED:
        logger.info(f"📧 Email disabled. Password reset link for {to_email}: {reset_url}")
        return

    if not settings.RESEND_API_KEY:
        logger.warning("⚠️ RESEND_API_KEY not configured. Cannot send reset email.")
        return

    if not settings.RESEND_FROM_EMAIL:
        logger.warning("⚠️ RESEND_FROM_EMAIL not configured. Cannot send reset email.")
        return

    try:
        # Escape user-provided URL to prevent XSS in HTML email
        safe_reset_url = html.escape(str(reset_url))

        html_content = f"""
        <!DOCTYPE html>
        <html>
            <head>
                <meta charset="utf-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
            </head>
            <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; background-color: #f5f5f5;">
                <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; text-align: center;">
                    <h1 style="color: white; margin: 0; font-size: 24px;">🔐 Reset Your Password</h1>
                </div>

                <div style="padding: 30px; background: #f9f9f9;">
                    <div style="background: white; padding: 25px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                        <p style="color: #333; font-size: 16px;">You requested a password reset. Click the button below to set a new password. This link expires in <strong>1 hour</strong>.</p>

                        <div style="text-align: center; margin: 30px 0;">
                            <a href="{safe_reset_url}"
                               style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                                      color: white; padding: 14px 28px; text-decoration: none;
                                      border-radius: 6px; font-weight: bold; font-size: 16px;
                                      display: inline-block;">
                                Reset Password
                            </a>
                        </div>

                        <p style="color: #666; font-size: 13px;">If you didn't request this, you can safely ignore this email. Your password won't change.</p>
                    </div>
                </div>

                <div style="padding: 20px; text-align: center; color: #666; font-size: 12px;">
                    <p style="margin: 5px 0;">EscabiAPI — Automated notification</p>
                </div>
            </body>
        </html>
        """

        resend.api_key = settings.RESEND_API_KEY

        params = {
            "from": f"EscabiAPI <{settings.RESEND_FROM_EMAIL}>",
            "to": [to_email],
            "subject": "🔐 Reset your EscabiAPI password",
            "html": html_content,
        }

        response = resend.Emails.send(params)
        logger.info(f"✅ Password reset email sent to {to_email}")
        logger.debug(f"Resend response: {response}")

    except Exception as e:
        # Non-raising: same guard as send_new_order_notification
        logger.error(f"❌ Error sending password reset email to {to_email}: {e}", exc_info=True)
