from pydantic import BaseModel


class ContactCreate(BaseModel):
    name: str
    title: str | None = None
    account: str | None = None
    email: str | None = None
    phone: str | None = None


class ContactRead(ContactCreate):
    id: str
