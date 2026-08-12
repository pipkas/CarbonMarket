"""
Доменные исключения приложения.

Все они перехватываются в main.py через exception_handler'ы FastAPI и
превращаются в JSON {"error": "...", "detail": "..."} с нужным HTTP-статусом.
"""


class DomainError(Exception):
    """Базовый класс для всех доменных ошибок."""
    http_status = 400


class AuthError(DomainError):
    """Неверный логин/пароль, просроченный или неизвестный токен."""
    http_status = 401


class UserAlreadyExistsError(DomainError):
    http_status = 409


class ListingNotFoundError(DomainError):
    http_status = 404


class VoucherNotFoundError(DomainError):
    http_status = 404


class InsufficientSellerCapacityError(DomainError):
    """
    Продавец пытается выставить на продажу больше УЕ, чем у него реально
    доступно (баланс в реестре минус уже замороженное под другие векселя
    минус уже выставленное в других активных объявлениях).
    """
    http_status = 422


class DealConstraintViolationError(DomainError):
    """
    Нарушение гибких правил объявления: запрошенное количество меньше
    min_deal_quantity или больше max_deal_quantity данного объявления.
    """
    http_status = 422


class InsufficientFundsError(DomainError):
    """
    У покупателя не хватает денег на балансе для оформления сделки.
    Деньги (как и УЕ у продавца) списываются/зачисляются в момент
    выпуска векселя, а не при обналичивании.
    """
    http_status = 402

    def __init__(self, required: float, available: float):
        self.required = required
        self.available = available
        super().__init__(
            f"Недостаточно средств: требуется {required:.2f} ₽, доступно {available:.2f} ₽"
        )


class VoucherNotCancellableError(DomainError):
    """
    Вексель нельзя отменить: хотя бы один из его компонентов уже обналичен
    (УЕ реально зачислены на баланс покупателя в реестре) — откатывать
    такую операцию небезопасно, либо вексель уже был отменён ранее.
    """
    http_status = 409


class InsufficientMarketSupplyError(DomainError):
    """
    Суммарно по всем подходящим активным объявлениям не набирается
    запрошенное количество УЕ (сценарий 1) — бросается вместе с данными
    о том, сколько максимально удалось бы собрать (partial_quantity),
    чтобы фронт мог предложить пользователю купить меньше или подождать.
    """
    http_status = 409

    def __init__(self, requested: float, best_available: float):
        self.requested = requested
        self.best_available = best_available
        super().__init__(
            f"Запрошено {requested}, максимум доступно на рынке: {best_available}"
        )
