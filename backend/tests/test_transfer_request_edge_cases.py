from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.schemas.transfer import TransferCreate
from app.services.stock_service import StockService


def transfer_payload(**overrides):
    payload = {
        "from_location_id": "source-location",
        "to_location_id": "destination-location",
        "assigned_to_id": "source-manager",
        "transfer_type": "consumable",
        "items": [{"item_id": "item-1", "quantity_requested": 1}],
    }
    payload.update(overrides)
    return payload


def test_source_responsible_person_is_required():
    payload = transfer_payload()
    payload.pop("assigned_to_id")

    with pytest.raises(ValidationError, match="assigned_to_id"):
        TransferCreate.model_validate(payload)


def test_cross_location_request_does_not_require_destination_responsible():
    request = TransferCreate.model_validate(transfer_payload())

    assert request.assigned_to_id == "source-manager"
    assert request.destination_responsible_id is None


@pytest.mark.parametrize(
    "overrides, message",
    [
        (
            {"to_location_id": "source-location"},
            "Select a destination responsible person",
        ),
        (
            {
                "to_location_id": "source-location",
                "destination_responsible_id": "destination-manager",
            },
            "Enter the receiving area/person",
        ),
        (
            {
                "to_location_id": "source-location",
                "destination_responsible_id": "destination-manager",
                "local_receiving_details": "   ",
            },
            "Enter the receiving area/person",
        ),
    ],
)
def test_same_location_request_requires_responsible_person_and_receiving_details(
    overrides, message
):
    with pytest.raises(ValidationError, match=message):
        TransferCreate.model_validate(transfer_payload(**overrides))


def test_same_location_request_accepts_complete_receiving_details():
    request = TransferCreate.model_validate(
        transfer_payload(
            to_location_id="source-location",
            destination_responsible_id="destination-manager",
            local_receiving_details="NDT lab bench - Ravi",
        )
    )

    assert request.local_receiving_details == "NDT lab bench - Ravi"


@pytest.mark.asyncio
async def test_reserve_stock_locks_row_and_can_defer_commit():
    stock = SimpleNamespace(quantity_on_hand=10, quantity_reserved=2)
    result = SimpleNamespace(scalar_one_or_none=lambda: stock)
    db = SimpleNamespace(
        execute=AsyncMock(return_value=result),
        flush=AsyncMock(),
        commit=AsyncMock(),
        refresh=AsyncMock(),
    )

    await StockService(db).reserve_stock(
        item_id="item-1",
        location_id="source-location",
        quantity=3,
        commit=False,
    )

    statement = db.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in sql
    assert stock.quantity_reserved == 5
    db.flush.assert_awaited_once()
    db.commit.assert_not_awaited()
    db.refresh.assert_not_awaited()
