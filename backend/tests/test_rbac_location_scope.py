"""Regression tests for the central RBAC location-scope rules."""

from types import SimpleNamespace

import pytest

from app.api.v1.dependencies import authorized_location_ids, require_location_access
from app.core.exceptions import AuthorizationError
from app.models.user import UserRole


def make_user(role: UserRole, *location_ids: str):
    return SimpleNamespace(
        role=role,
        assigned_locations=[SimpleNamespace(id=value) for value in location_ids],
        has_all_location_access=role in (UserRole.ADMIN, UserRole.HEAD_OFFICE_MANAGER),
        has_location_access=lambda value: (
            role in (UserRole.ADMIN, UserRole.HEAD_OFFICE_MANAGER)
            or value in location_ids
        ),
    )


@pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.HEAD_OFFICE_MANAGER])
def test_company_wide_roles_have_unrestricted_location_scope(role):
    user = make_user(role)

    assert authorized_location_ids(user) is None
    require_location_access(user, "head-office")


def test_location_manager_is_limited_to_assigned_locations():
    user = make_user(UserRole.LOCATION_MANAGER, "location-y")

    assert authorized_location_ids(user) == ["location-y"]
    require_location_access(user, "location-y")

    with pytest.raises(AuthorizationError):
        require_location_access(user, "head-office")


def test_unassigned_location_manager_has_no_location_access():
    user = make_user(UserRole.LOCATION_MANAGER)

    assert authorized_location_ids(user) == []
    with pytest.raises(AuthorizationError):
        require_location_access(user, None)
    with pytest.raises(AuthorizationError):
        require_location_access(user, "location-y")
