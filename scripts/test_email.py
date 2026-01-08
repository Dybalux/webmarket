"""
Script de diagnóstico para conexión SMTP.
Ejecutar: python scripts/test_email.py
"""
import smtplib
import socket
import sys
import logging
from pathlib import Path

# Agregar el directorio raíz al path para importar config
sys.path.append(str(Path(__file__).parent.parent))

from config import settings

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def check_connectivity():
    host = settings.SMTP_HOST
    port = settings.SMTP_PORT
    user = settings.SMTP_USER
    
    logger.info("🔍 Iniciando diagnóstico de conexión SMTP...")
    logger.info(f"⚙️  Configuración: Host={host}, Port={port}, User={user}, SSL={port==465}")

    # 1. Prueba de resolución DNS
    logger.info(f"1️⃣  Probando resolución DNS de {host}...")
    try:
        ip_address = socket.gethostbyname(host)
        logger.info(f"✅ DNS resuelto correctamente: {host} -> {ip_address}")
    except socket.gaierror as e:
        logger.error(f"❌ Error DNS: No se pudo resolver {host}. Detalles: {e}")
        return

    # 2. Prueba de conectividad TCP básica
    logger.info(f"2️⃣  Probando conexión TCP a {host}:{port}...")
    try:
        sock = socket.create_connection((host, port), timeout=10)
        sock.close()
        logger.info(f"✅ Conexión TCP exitosa a {host}:{port}")
    except OSError as e:
        logger.error(f"❌ Error de conexión TCP: {e}")
        logger.error("   Posibles causas: Firewall bloqueando el puerto, falta de internet, o configuración de red incorrecta (Docker/VPN).")
        return

    # 3. Prueba de protocolo SMTP
    logger.info(f"3️⃣  Probando sesión SMTP...")
    server = None
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=10)
        else:
            server = smtplib.SMTP(host, port, timeout=10)
        
        server.set_debuglevel(1)  # Ver detalles de la conversación SMTP
        server.ehlo()
        logger.info("✅ Saludo EHLO exitoso")
        
        if port == 587:
            logger.info("🔒 Iniciando STARTTLS...")
            server.starttls()
            server.ehlo()
            logger.info("✅ STARTTLS completado")
            
        # 4. Prueba de Autenticación
        if user and settings.SMTP_PASSWORD:
            logger.info(f"4️⃣  Probando autenticación con usuario {user}...")
            server.login(user, settings.SMTP_PASSWORD)
            logger.info("✅ Autenticación exitosa")
        else:
            logger.info("ℹ️  Saltando autenticación (credenciales no configuradas)")

        logger.info("🎉 ¡Todas las pruebas de conectividad pasaron correctamente!")
        
    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"❌ Error de autenticación: {e}")
        logger.error("   Verifica tu usuario y contraseña (o App Password).")
    except Exception as e:
        logger.error(f"❌ Error SMTP: {e}")
    finally:
        if server:
            try:
                server.quit()
            except:
                pass

if __name__ == "__main__":
    check_connectivity()
