# Service Layer Guidelines

## Service Class Pattern

```python
import logging
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.some_module import SomeModel

logger = logging.getLogger(__name__)


class SomeService:
    """Service for managing [domain] operations."""

    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, id: UUID) -> SomeModel | None:
        return self.db.get(SomeModel, id)

    def list_all(self, *, limit: int = 100) -> list[SomeModel]:
        stmt = select(SomeModel).limit(limit)
        return list(self.db.scalars(stmt).all())

    def create(self, data: SomeCreateSchema) -> SomeModel:
        record = SomeModel(**data.model_dump())
        self.db.add(record)
        self.db.flush()
        logger.info("Created %s: %s", SomeModel.__name__, record.id)
        return record
```

## Key Rules

1. **Receive db in __init__** — Service owns the session reference
2. **Don't commit** — Let the caller (route/task) handle commit
3. **Use flush() for IDs** — When you need generated IDs before commit
4. **Log important operations** — Creates, updates, deletes
5. **Type hint everything** — All parameters and return types

## Querying Pattern

```python
# Use select() with scalars() for lists
stmt = select(Model).where(Model.status == "ACTIVE")
items = list(self.db.scalars(stmt).all())

# Use db.get() for single record by PK
record = self.db.get(Model, record_id)

# Use scalar() for single result from query
stmt = select(Model).where(Model.number == number)
record = self.db.scalar(stmt)
```

## Error Handling

Services raise domain exceptions (`ValueError`, `RuntimeError`), NOT `HTTPException`.
Routes translate exceptions to HTTP responses.
