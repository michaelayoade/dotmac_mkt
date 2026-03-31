"""CRUD for the campaign_members junction table."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import delete, insert, select, update
from sqlalchemy.orm import Session

from app.models.campaign import Campaign, CampaignMemberRole, campaign_members
from app.models.person import Person

logger = logging.getLogger(__name__)


class CampaignMemberService:
    """Manage campaign membership (the campaign_members junction table)."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def add_member(
        self,
        campaign_id: UUID,
        person_id: UUID,
        *,
        role: CampaignMemberRole = CampaignMemberRole.contributor,
    ) -> None:
        """Add a person to a campaign. Raises ValueError if campaign not found."""
        campaign = self.db.get(Campaign, campaign_id)
        if campaign is None:
            raise ValueError(f"Campaign {campaign_id} not found")
        self.db.execute(
            insert(campaign_members).values(
                campaign_id=campaign_id,
                person_id=person_id,
                role=role,
            )
        )
        self.db.flush()
        logger.info(
            "Added member %s to Campaign %s as %s",
            person_id,
            campaign_id,
            role.value,
        )

    def remove_member(self, campaign_id: UUID, person_id: UUID) -> None:
        """Remove a person from a campaign."""
        self.db.execute(
            delete(campaign_members).where(
                campaign_members.c.campaign_id == campaign_id,
                campaign_members.c.person_id == person_id,
            )
        )
        self.db.flush()
        logger.info("Removed member %s from Campaign %s", person_id, campaign_id)

    def list_members(self, campaign_id: UUID) -> list[dict]:
        """List all members of a campaign.

        Returns list of dicts with keys: person_id, role, person.
        Raises ValueError if campaign not found.
        """
        campaign = self.db.get(Campaign, campaign_id)
        if campaign is None:
            raise ValueError(f"Campaign {campaign_id} not found")
        stmt = (
            select(campaign_members.c.person_id, campaign_members.c.role, Person)
            .join(Person, Person.id == campaign_members.c.person_id)
            .where(campaign_members.c.campaign_id == campaign_id)
        )
        rows = self.db.execute(stmt).all()
        return [{"person_id": row[0], "role": row[1], "person": row[2]} for row in rows]

    def update_role(
        self,
        campaign_id: UUID,
        person_id: UUID,
        *,
        role: CampaignMemberRole,
    ) -> None:
        """Update a member's role. Raises ValueError if membership not found."""
        result = self.db.execute(
            update(campaign_members)
            .where(
                campaign_members.c.campaign_id == campaign_id,
                campaign_members.c.person_id == person_id,
            )
            .values(role=role)
        )
        if result.rowcount == 0:
            raise ValueError(
                f"Person {person_id} is not a member of Campaign {campaign_id}"
            )
        self.db.flush()
        logger.info(
            "Updated role for %s in Campaign %s to %s",
            person_id,
            campaign_id,
            role.value,
        )

    def is_member(self, campaign_id: UUID, person_id: UUID) -> bool:
        """Check if a person is a member of a campaign."""
        stmt = select(campaign_members.c.person_id).where(
            campaign_members.c.campaign_id == campaign_id,
            campaign_members.c.person_id == person_id,
        )
        return self.db.execute(stmt).first() is not None
