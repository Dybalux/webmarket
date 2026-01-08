"""
Servicio simple de email para notificar a admins sobre nuevas órdenes.
"""
import smtplib
import socket
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from config import settings
import logging

logger = logging.getLogger(__name__)


async def send_new_order_notification(order_id: str, user_email: str, total_amount: float, payment_method: str):
    """
    Envía un email a TODOS los admins notificando sobre una nueva orden.
    
    Args:
        order_id: ID de la orden creada
        user_email: Email del usuario que hizo la orden
        total_amount: Monto total de la orden
        payment_method: Método de pago seleccionado
    """
    # Si el email no está habilitado, solo loguear
    if not settings.EMAIL_ENABLED:
        logger.info(f"📧 Email deshabilitado. Nueva orden #{order_id} - ${total_amount} - {payment_method}")
        return
    
    # Validar configuración SMTP
    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        logger.warning("⚠️ Configuración SMTP incompleta. No se puede enviar notificación.")
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
        
        # Crear mensaje
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f'🛒 Nueva Orden #{order_id} - {payment_method}'
        msg['From'] = settings.SMTP_USER
        msg['To'] = ', '.join(admin_emails)  # Múltiples destinatarios
        
        # Contenido HTML
        html = f"""
        <html>
            <body style="font-family: Arial, sans-serif;">
                <h2 style="color: #4CAF50;">🛒 Nueva Orden Recibida</h2>
                <div style="background: #f5f5f5; padding: 20px; border-radius: 5px;">
                    <p><strong>Orden:</strong> #{order_id}</p>
                    <p><strong>Cliente:</strong> {user_email}</p>
                    <p><strong>Total:</strong> ${total_amount:,.2f}</p>
                    <p><strong>Método de Pago:</strong> {payment_method}</p>
                </div>
                <p style="margin-top: 20px;">
                    {'⚠️ <strong>Requiere confirmación manual de pago por transferencia</strong>' if payment_method == 'Transferencia Bancaria' else '✅ Pago procesado automáticamente por Mercado Pago'}
                </p>
                <hr>
                <p style="color: #666; font-size: 12px;">EscabiAPI - Sistema de Notificaciones</p>
            </body>
        </html>
        """
        
        # Contenido texto plano (fallback)
        text = f"""
        Nueva Orden Recibida
        
        Orden: #{order_id}
        Cliente: {user_email}
        Total: ${total_amount:,.2f}
        Método de Pago: {payment_method}
        
        {'Requiere confirmación manual de pago' if payment_method == 'Transferencia Bancaria' else 'Pago procesado automáticamente'}
        """
        
        part1 = MIMEText(text, 'plain')
        part2 = MIMEText(html, 'html')
        msg.attach(part1)
        msg.attach(part2)
        
        # Enviar email a todos los admins
        # Enviar email a todos los admins
        # Implementación robusta para entornos Docker/Railway con problemas de IPv6
        try:
            # Intentar conexión estándar
            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20)
        except OSError as e:
            # [Errno 101] Network unreachable suele ocurrir cuando intenta usar IPv6 en un entorno sin soporte
            if e.errno == 101:
                logger.warning(f"⚠️ Error de red (Errno 101) con {settings.SMTP_HOST}. Reintentando forzando IPv4...")
                # Resolver DNS manualmente a IPv4
                ip_address = socket.gethostbyname(settings.SMTP_HOST)
                # Conectar directamente a la IP
                server = smtplib.SMTP(ip_address, settings.SMTP_PORT, timeout=20)
                # HACK CRÍTICO: Restaurar el hostname original para que starttls() valido el certificado correctamente
                server._host = settings.SMTP_HOST
            else:
                raise e

        # Usar el servidor conectado
        with server:
            server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)
        
        logger.info(f"✅ Email enviado a {len(admin_emails)} admin(s): Nueva orden #{order_id}")
        
    except Exception as e:
        # No romper la aplicación si falla el email
        logger.error(f"❌ Error al enviar email de notificación: {e}", exc_info=True)
