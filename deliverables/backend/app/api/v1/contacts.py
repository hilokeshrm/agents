"""
Contacts (WBS-adjacent, added for the UI build): the one genuinely new entity in
this pass. Unlike accounts and products (app/api/v1/accounts.py, products.py),
a contact is not derivable from anything already on Opportunity -- the real
Funnel/ProjectTrack data has no person-level fields at all. This list starts
empty and stays empty until someone adds a real name; nothing is seeded.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.contact import Contact
from app.db.session import get_db
from app.schemas.contact import ContactCreate, ContactRead

router = APIRouter(prefix="/contacts", tags=["contacts"])


@router.get("", response_model=list[ContactRead])
def list_contacts(db: Session = Depends(get_db)) -> list[ContactRead]:
    stmt = select(Contact).order_by(Contact.created_at.desc())
    return list(db.scalars(stmt).all())


@router.post("", response_model=ContactRead, status_code=201)
def create_contact(payload: ContactCreate, db: Session = Depends(get_db)) -> ContactRead:
    contact = Contact(**payload.model_dump())
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


@router.delete("/{contact_id}", status_code=204)
def delete_contact(contact_id: str, db: Session = Depends(get_db)) -> None:
    contact = db.get(Contact, contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="Contact not found")
    db.delete(contact)
    db.commit()
