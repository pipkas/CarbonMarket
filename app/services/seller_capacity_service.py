"""
Определяет, сколько УЕ данных характеристик продавец реально может
заминтить (выпустить) в новый вексель.

УПРОЩЕНИЕ ПОСЛЕ СМЕНЫ МОДЕЛИ: раньше Listing лишь "виртуально"
резервировал объём УЕ (сама заморозка в реестре происходила только в
момент покупки), поэтому нужно было отдельно вычитать объём, уже
выставленный в ДРУГИХ активных объявлениях продавца — иначе один и тот
же остаток можно было бы выставить на продажу дважды.

Теперь вексель (Voucher) выпускается ДО того, как его выставляют на
продажу, и сама операция выпуска (voucher_service.mint_voucher) сразу
замораживает нужный объём в реестре (registry_client.freeze_units).
Поэтому available_quantity, которую отдаёт registry_client.get_balance,
уже полностью учитывает всё, что было заминчено ранее — двойного учёта
объявлений больше нет и вычитать из него нечего.
"""
from app.models.carbon_unit import CarbonUnitCharacteristics
from app.services.registry_client import registry_client


def get_available_to_mint(seller_registry_account_id: str, characteristics: CarbonUnitCharacteristics) -> float:
    batches = registry_client.get_balance(seller_registry_account_id, characteristics)
    return sum(b.available_quantity for b in batches)
