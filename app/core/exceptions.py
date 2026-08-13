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
    Продавец пытается заминтить (выпустить) вексель на больший объём УЕ,
    чем у него реально доступно на счету в реестре по этим характеристикам.
    """
    http_status = 422


class VoucherNotOwnedError(DomainError):
    """
    Действие с векселем (выставить на продажу, обналичить, отменить
    покупку) может совершать только его ТЕКУЩИЙ держатель.
    """
    http_status = 403


class VoucherAlreadyRedeemedError(DomainError):
    """Вексель уже обналичен — с ним больше нельзя ничего сделать (перепродать, обналичить повторно)."""
    http_status = 409


class VoucherAlreadyListedError(DomainError):
    """У этого векселя уже есть активное объявление о продаже — второе выставить нельзя."""
    http_status = 409


class TransferNotCancellableError(DomainError):
    """
    Отменить можно только САМУЮ ПОСЛЕДНЮЮ покупку данного векселя — и
    только пока его не перепродали дальше и не обналичили.
    """
    http_status = 409


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
