"""
Определяет, сколько УЕ данных характеристик продавец реально может
выставить на продажу (ТЗ, сценарий 3):

  доступно_для_продажи =
      баланс_в_реестре(характеристики)                       # registry_client.get_balance
      - уже_заморожено_под_другие_векселя                    # batch.frozen_quantity (это уже учтено в available_quantity)
      - уже_выставлено_в_ДРУГИХ_активных_объявлениях          # remaining_quantity других Listing с теми же характеристиками

Последний пункт важен: пока объявление активно, продавец не должен иметь
возможность создать второе объявление на тот же (или пересекающийся) объём
УЕ — иначе можно продать один и тот же УЕ дважды до момента заморозки.
Мы вычитаем remaining_quantity всех АКТИВНЫХ объявлений продавца с
характеристиками, пересекающимися с запрашиваемыми.
"""
from app.models.carbon_unit import CarbonUnitCharacteristics
from app.repositories.listing_repo import get_active_by_seller
from app.services.registry_client import registry_client


def get_available_for_sale(seller_registry_account_id: str, seller_id: str, characteristics: CarbonUnitCharacteristics) -> float:
    batches = registry_client.get_balance(seller_registry_account_id, characteristics)
    registry_available = sum(b.available_quantity for b in batches)

    already_listed = sum(
        l.remaining_quantity
        for l in get_active_by_seller(seller_id)
        if l.characteristics.matches(characteristics) or characteristics.matches(l.characteristics)
    )

    return max(0.0, registry_available - already_listed)
