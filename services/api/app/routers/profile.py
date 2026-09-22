"""Career preferences and academic profile (``user_profiles``)."""

from fastapi import APIRouter, HTTPException, Response, status

from app.core.deps import CurrentUser, DbSession
from app.models.user import UserProfile
from app.schemas.profile import ProfileResponse, ProfileUpdate

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get(
    "",
    response_model=ProfileResponse,
    responses={status.HTTP_404_NOT_FOUND: {"description": "Profile not created yet"}},
)
async def get_profile(user: CurrentUser, db: DbSession) -> ProfileResponse:
    """Return the current user's profile, or 404 if they have not created one."""
    profile = await db.get(UserProfile, user.id)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not created yet")
    return ProfileResponse.model_validate(profile)


@router.put(
    "",
    response_model=ProfileResponse,
    responses={status.HTTP_201_CREATED: {"model": ProfileResponse}},
)
async def upsert_profile(
    body: ProfileUpdate, user: CurrentUser, db: DbSession, response: Response
) -> ProfileResponse:
    """Create the profile (201) or merge the supplied fields into it (200).

    Only fields present in the request body are written; omitted fields keep
    their current values. Send ``null`` to clear a scalar field or ``[]`` to
    clear a list.
    """
    profile = await db.get(UserProfile, user.id)
    created = profile is None
    if profile is None:
        # Initialise array columns explicitly so the response is well-formed even
        # before the ORM's Python-side defaults are applied at flush time.
        profile = UserProfile(
            user_id=user.id,
            preferred_roles=[],
            preferred_locations=[],
            preferred_work_mode=[],
            skills=[],
        )
        db.add(profile)

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)

    await db.commit()
    await db.refresh(profile)

    if created:
        response.status_code = status.HTTP_201_CREATED
    return ProfileResponse.model_validate(profile)
