"""Application branding endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.v1.dependencies import DB, CurrentUser, require_admin_or_ho_manager
from app.models.branding import AppBranding
from app.schemas.branding import BrandingResponse, BrandingUpdate

router = APIRouter()

DEFAULT_BRANDING_ID = "default"


async def get_or_create_branding(db: DB) -> AppBranding:
    result = await db.execute(select(AppBranding).where(AppBranding.id == DEFAULT_BRANDING_ID))
    branding = result.scalar_one_or_none()
    if branding:
        return branding

    branding = AppBranding(
        id=DEFAULT_BRANDING_ID,
        company_name="M/s. SCIENTECH SERVICES",
        app_name="Scientech-IMS",
        logo_data_url=None,
    )
    db.add(branding)
    await db.commit()
    await db.refresh(branding)
    return branding


@router.get("", response_model=BrandingResponse)
async def get_branding(db: DB) -> BrandingResponse:
    """Get application branding. Public so the login page can use it."""
    branding = await get_or_create_branding(db)
    return BrandingResponse.model_validate(branding)


@router.put("", response_model=BrandingResponse)
async def update_branding(
    request: BrandingUpdate,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_admin_or_ho_manager),
) -> BrandingResponse:
    """Update application branding."""
    branding = await get_or_create_branding(db)
    data = request.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(branding, key, value)
    await db.commit()
    await db.refresh(branding)
    return BrandingResponse.model_validate(branding)

