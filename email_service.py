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
        
        # Helper interno para conectar de forma robusta
        def connect_smtp(host, port):
            use_ssl = (port == 465)
            connection_class = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
            timeout = 30  # Timeout aumentado
            
            try:
                # Intento 1: Conexión estándar
                server = connection_class(host, port, timeout=timeout)
            except OSError as e:
                # Fallback IPv4 para errores de red (101 Network unreachable, etc)
                if e.errno == 101 or "unreachable" in str(e).lower(): 
                    logger.warning(f"⚠️ Error de red con {host}. Reintentando con IPv4...")
                    try:
                        ip_address = socket.gethostbyname(host)
                        server = connection_class(ip_address, port, timeout=timeout)
                        # HACK: Restaurar hostname para validación SSL/TLS
                        server._host = host 
                    except Exception as fallback_error:
                         # Si falla el fallback, lanzar el error original para no ocultarlo
                         raise e
                else:
                    raise e
            return server

        try:
            server = connect_smtp(settings.SMTP_HOST, settings.SMTP_PORT)
            
            with server:
                # Si NO es SSL (puerto 465), necesitamos STARTTLS
                if settings.SMTP_PORT != 465:
                    server.starttls()
                
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)
                
        except Exception as e:
            # Re-lanzar para que lo atrape el bloque except exterior
            raise e
        
        logger.info(f"✅ Email enviado a {len(admin_emails)} admin(s): Nueva orden #{order_id}")
        
    except Exception as e:
        # No romper la aplicación si falla el email
        logger.error(f"❌ Error al enviar email de notificación: {e}", exc_info=True)
