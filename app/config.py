"""
Конфигурация приложения.

Сейчас — просто константы. При переходе на реальный реестр УЕ и реальную БД
сюда переезжают переменные окружения (pydantic-settings BaseSettings):
REGISTRY_API_URL, REGISTRY_API_KEY, DATABASE_URL, JWT_SECRET, JWT_TTL_SECONDS.
"""

class Settings:
    APP_NAME = "Carbon Market API"

    # Заглушка: TTL токена аутентификации (сек)
    AUTH_TOKEN_TTL_SECONDS = 60 * 60 * 12

    # Заглушка: базовая "точность" сопоставления характеристик УЕ.
    # Если покупатель не указал часть характеристик — считаем, что подходит
    # любое значение по неуказанным полям.
    STRICT_CHARACTERISTIC_MATCH = False

    # Режимы ценообразования у продавца
    PRICING_MODE_PER_UNIT_MARKUP = "PER_UNIT_MARKUP"   # наценка на единицу
    PRICING_MODE_FLAT_FEE_PER_DEAL = "FLAT_FEE_PER_DEAL"  # комиссия за сделку


settings = Settings()
