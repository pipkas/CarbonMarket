"""
DTO для характеристик УЕ — используется и как фильтр покупателя, и как
описание того, что продаёт продавец. Все поля опциональны намеренно.
"""
from datetime import date

from pydantic import BaseModel

from app.models.carbon_unit import ProjectType, UnitStatus


class CharacteristicsFilterDTO(BaseModel):
    project_name: str | None = None
    project_type: ProjectType | None = None
    vintage_year: int | None = None
    methodology: str | None = None
    verifier: str | None = None
    issue_date: date | None = None
    country: str | None = None
    status: UnitStatus | None = None
