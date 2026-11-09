from unittest.mock import AsyncMock

import pytest

from app.schemas.item import ItemCreate, ItemUpdate
from app.services.item_service import ItemService


@pytest.mark.parametrize("value", [None, "", "   "])
def test_item_create_accepts_missing_or_blank_sku(value):
    item = ItemCreate.model_validate(
        {
            "sku": value,
            "name": "Couplant Gel",
            "category_id": "cat-consumable",
        }
    )

    assert item.sku is None


def test_item_update_converts_blank_sku_to_none_for_clearing():
    item = ItemUpdate.model_validate({"sku": "   "})

    assert item.model_dump(exclude_unset=True) == {"sku": None}


@pytest.mark.asyncio
async def test_blank_sku_lookup_does_not_query_database():
    db = AsyncMock()

    result = await ItemService(db).get_by_sku("  ")

    assert result is None
    db.execute.assert_not_awaited()
