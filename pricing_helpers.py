from datetime import datetime
from typing import Optional
from models import DynamicPricingSettings
import logging

logger = logging.getLogger(__name__)

def is_dynamic_pricing_active(settings: DynamicPricingSettings, current_time: Optional[datetime] = None) -> bool:
    """
    Verifica si el ajuste de precios dinámico está activo en el momento actual.
    """
    if not settings.enabled:
        return False

    if current_time is None:
        current_time = datetime.utcnow()

    # Obtener día (1=Lunes, 7=Domingo) y hora (0-23)
    current_day = current_time.weekday() + 1
    current_hour = current_time.hour

    # Lógica de rango de días
    # Si el día actual está fuera del rango [start_day, end_day]
    # Nota: Esto no maneja rangos que cruzan el lunes (ej: Domingo a Martes), 
    # pero para "Viernes a Domingo" funciona perfecto.
    if not (settings.start_day <= current_day <= settings.end_day):
        return False

    # Lógica de horas
    if settings.start_hour == settings.end_hour:
        # Si las horas son iguales, se considera activo todo el día en el rango de días
        return True

    if settings.start_hour < settings.end_hour:
        # Rango normal (ej: 08:00 a 20:00)
        return settings.start_hour <= current_hour < settings.end_hour
    else:
        # Rango nocturno (ej: 20:00 a 06:00)
        # Activo si es tarde en la noche O temprano en la mañana
        return current_hour >= settings.start_hour or current_hour < settings.end_hour

def get_adjusted_price(base_price: float, settings: DynamicPricingSettings) -> float:
    """
    Calcula el precio ajustado basándose en la configuración de precios dinámicos.
    """
    if is_dynamic_pricing_active(settings):
        adjusted_price = base_price * settings.multiplier
        return round(adjusted_price, 2)
    return base_price
