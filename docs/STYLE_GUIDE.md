# Style Guide — dobs Clean Architecture Refactor

Derived from the `eclipse` reference codebase (`backend(2)`). Every pattern below
is backed by concrete code from that codebase. Adapt to the dobs domain
(bank-statement extraction, not user management) but follow the structural
conventions exactly.

---

## 1. Directory Layout

```
src/dobs/
├── domain/                  # Pure business logic, no I/O, no frameworks
│   ├── common/              # Shared domain primitives (Specification base)
│   ├── entities/            # Mutable aggregate roots and identifiers
│   ├── value_objects/       # Immutable typed values (enums, small frozen dataclasses)
│   ├── specifications/      # Composable query predicates
│   └── errors.py            # DomainError hierarchy
│
├── application/             # Use cases — orchestrates domain + ports
│   ├── commands/            # Write-side use cases (grouped by subdomain)
│   │   ├── extraction/      # extract_statement.py, repair_statement.py, ...
│   │   └── cache/           # bust_cache.py, clear_cache.py
│   ├── queries/             # Read-side use cases
│   │   ├── get_extraction_result.py
│   │   ├── get_audit_log.py
│   │   └── get_cache_keys.py
│   ├── services/            # Cross-cutting application services
│   ├── common/              # Shared DTOs: pagination, list_result, sorting
│   ├── ports/               # Protocol interfaces (the dependency inversion seam)
│   │   ├── llm_backend.py
│   │   ├── cache.py
│   │   ├── audit_sink.py
│   │   ├── ocr_engine.py
│   │   ├── vendor_lookup.py
│   │   ├── event_bus.py
│   │   └── __init__.py      # Re-exports for short imports
│   ├── config.py            # Application-layer frozen config dataclasses
│   └── errors.py            # ApplicationError hierarchy
│
├── infrastructure/          # Concrete implementations of ports
│   ├── adapters/
│   │   ├── llm/             # anthropic_backend.py, ollama_backend.py
│   │   ├── cache/           # sqlite_cache.py, redis_cache.py, memory_cache.py
│   │   ├── ocr/             # tesseract_engine.py, vision_engine.py
│   │   ├── audit/           # sqlite_audit_sink.py
│   │   ├── vendor/          # clearbit_vendor_lookup.py, seed_vendor_lookup.py
│   │   ├── security/        # prompt_sanitizer.py
│   │   └── telemetry/       # otel_tracer.py, call_stats_collector.py
│   └── persistence/         # (future) if migrating to async DB
│
├── presentation/            # Transport layer — HTTP, CLI, gRPC, Streamlit
│   ├── api/
│   │   └── http/
│   │       ├── v1/
│   │       │   ├── extraction/  # router.py, schemas.py
│   │       │   ├── audit/       # router.py, schemas.py
│   │       │   ├── cache/       # router.py, schemas.py
│   │       │   ├── health/      # router.py
│   │       │   └── telemetry/   # router.py
│   │       ├── common/          # exc_handlers.py, schemas.py
│   │       └── middleware/      # tenant.py, api_key.py, cors.py
│   ├── cli/                 # click entry point
│   ├── grpc/                # gRPC transport (optional)
│   └── streamlit/           # Streamlit UI (optional)
│
└── main/                    # Composition root — wires everything
    ├── config/
    │   ├── settings.py      # pydantic-settings
    │   └── logging.py       # structlog setup
    ├── di/
    │   ├── container.py     # dishka container factory
    │   └── providers/       # one Provider per concern
    │       ├── handlers.py
    │       ├── config.py
    │       ├── llm.py
    │       ├── cache.py
    │       └── ...
    └── entrypoints/
        ├── web/             # factory.py, __main__.py
        └── cli/             # factory.py, __main__.py
```

Reference: `eclipse` uses this exact 5-layer split. From
`backend(2)/src/eclipse/`:

```
eclipse/
├── domain/
├── application/
├── infrastructure/
├── presentation/
└── main/
```

---

## 2. Naming Conventions

### 2.1 Command files: `<verb>_<noun>.py`

Each file contains a frozen `Command` dataclass, an optional frozen `Result`
dataclass, and a `Handler` class.

From `eclipse/application/commands/users/create_user.py`:

```python
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from eclipse.domain.value_objects.role import Role
from eclipse.domain.value_objects.user_status import UserStatus


@dataclass(frozen=True, kw_only=True, slots=True)
class CreateUserCommand:
    full_name: str
    personnel_number: str
    role: Role
    email: str
    password: str


@dataclass(frozen=True, kw_only=True, slots=True)
class CreateUserResult:
    oid: UUID
    full_name: str
    personnel_number: str
    role: Role
    email: str
    status: UserStatus
    created_at: datetime


class CreateUserHandler(FullNameMixin, EmailMixin):
    def __init__(
        self,
        /,
        *,
        authorization: Authorization,
        user_repository: UserRepository,
        password_hasher: PasswordHasher,
        password_validator: PasswordValidator,
        uuid_generator: UUIDGenerator,
        transaction_manager: TransactionManager,
    ) -> None:
        self._authorization = authorization
        self._user_repository = user_repository
        # ... store all deps as _private

    async def __call__(self, command: CreateUserCommand) -> CreateUserResult:
        # use-case logic here
        ...
```

### 2.2 Query files: `get_<noun>.py`

Same pattern: frozen `Query` dataclass, frozen `Result` dataclass, `Handler`.

From `eclipse/application/queries/get_users_list.py`:

```python
@dataclass(frozen=True, kw_only=True, slots=True)
class GetUsersListQuery:
    pagination: Pagination
    search: str | None = None
    role: Role | None = None
    is_active: bool | None = None
    sort_by: SortBy = SortBy.IS_ACTIVE
    sort_order: SortOrder = SortOrder.DESC


@dataclass(frozen=True, kw_only=True, slots=True)
class GetUsersListResult:
    users: list[UserListItem]
    pagination: PaginationResult


class GetUsersListHandler:
    def __init__(
        self,
        /,
        *,
        authorization: Authorization,
        user_repository: UserRepository,
    ) -> None:
        self._authorization = authorization
        self._user_repository = user_repository

    async def __call__(self, query: GetUsersListQuery) -> GetUsersListResult:
        ...
```

### 2.3 Port files: Protocol interfaces

From `eclipse/application/ports/system/transaction_manager.py`:

```python
from abc import abstractmethod
from typing import Protocol


class TransactionManager(Protocol):
    @abstractmethod
    async def flush(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def commit(self) -> None:
        raise NotImplementedError
```

From `eclipse/application/ports/auth/request_manager.py`:

```python
class RequestManager(Protocol):
    @abstractmethod
    def get_session_id_from_request(self) -> str | None:
        raise NotImplementedError

    @abstractmethod
    def add_session_id_to_request(self, session_id: str) -> None:
        raise NotImplementedError
```

Pattern: `Protocol` class, every method `@abstractmethod`, body is
`raise NotImplementedError`.

### 2.4 Adapter files: concrete implementations

Naming: `SQLAlchemy<Thing>`, `Bcrypt<Thing>`, `Cookie<Thing>`, etc.
For dobs: `Anthropic<Thing>`, `Ollama<Thing>`, `Sqlite<Thing>`,
`Redis<Thing>`, `Tesseract<Thing>`, `Clearbit<Thing>`.

From `eclipse/infrastructure/adapters/system/transaction_manager.py`:

```python
class SQLAlchemyTransactionManager(TransactionManager):
    def __init__(self, session: AsyncSession, unique_violations: UniqueViolations) -> None:
        self._session = session
        self._unique_violations = unique_violations

    async def flush(self) -> None:
        try:
            await self._session.flush()
        except IntegrityError as e:
            ...

    async def commit(self) -> None:
        await self._session.commit()
```

### 2.5 Entity conventions

- `@dataclass(eq=False, kw_only=True)` -- mutable, identity by OID.
- Inherit from `Entity[OIDType]` base.
- Factory: `@classmethod def create(cls, *, ...) -> Self`.
- Domain methods mutate in-place (e.g., `user.archive()`).
- Domain invariant violations raise `DomainError` subclasses.

### 2.6 Value object conventions

- `@dataclass(frozen=True, slots=True)` or `StrEnum`.
- No methods that cause side effects.

From `eclipse/domain/value_objects/role.py`:

```python
from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    OPERATOR = "operator"
```

From `eclipse/domain/value_objects/point.py`:

```python
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Point:
    x: float
    y: float
```

---

## 3. Async Patterns

### 3.1 `async def __call__` on handlers

Every handler's entry point is `async def __call__`. This makes handlers
callable objects that dishka can inject and routers can `await`.

From `eclipse/application/commands/auth/login.py`:

```python
class LoginHandler:
    # __init__ with DI ...

    async def __call__(self, command: LoginCommand) -> None:
        user = await self._user_repository.get(
            UserHasPersonnelNumber(command.personnel_number)
        )
        if user is None:
            raise UserNotFoundError
        if not user.is_active:
            raise UserInactiveError
        # ... business logic ...
        await self._transaction_manager.commit()
```

### 3.2 Transaction manager pattern

The handler calls `await self._transaction_manager.commit()` explicitly.
No implicit auto-commit. Flush before commit when you need the DB to
validate constraints early.

```python
self._user_repository.add(user)
await self._transaction_manager.flush()
await self._transaction_manager.commit()
```

For dobs: since we use SQLite, the "transaction manager" will be simpler
(context-manager around SQLite connection), but the protocol stays the same.

### 3.3 For dobs specifically

The pipeline is currently sync with `ThreadPoolExecutor`. The refactored
version makes handlers `async def __call__` but the LLM calls (httpx under
anthropic SDK) are blocking. Strategy:

- Handlers are `async def __call__`.
- LLM port methods are `async def call_structured(...)`.
- Anthropic adapter uses `httpx.AsyncClient` (the anthropic SDK supports
  `AsyncAnthropic`).
- CPU-bound work (Tesseract OCR, regex parsing, reconcile) runs in
  `asyncio.to_thread()`.
- The sync `extract()` entry point wraps with `asyncio.run()`.

---

## 4. Dependency Injection Patterns

### 4.1 Constructor injection with `/, *, kw_only`

Every handler and service uses this exact signature shape:

```python
class SomeHandler:
    def __init__(
        self,
        /,           # positional-only self
        *,           # everything else is keyword-only
        some_port: SomePort,
        other_port: OtherPort,
    ) -> None:
        self._some_port = some_port
        self._other_port = other_port
```

The `/` makes `self` positional-only; `*` forces all dependencies to be
keyword-only. This is a dishka convention that enables auto-wiring.

### 4.2 Dishka container wiring

From `eclipse/main/di/container.py`:

```python
from dishka import make_async_container

def create_container():
    settings = get_settings()
    context = {
        AppSettings: settings.app,
        PostgresSettings: settings.postgres,
        SessionSettings: settings.auth_session,
    }
    return make_async_container(
        *get_providers(),
        context=context,
    )
```

Providers are grouped by concern. From `eclipse/main/di/providers/handlers.py`:

```python
from dishka import Provider, Scope, provide_all


class HandlersProvider(Provider):
    scope = Scope.REQUEST

    handlers = provide_all(
        LoginHandler,
        LogoutHandler,
        CreateUserHandler,
        GetCurrentUserHandler,
        GetUsersListHandler,
        # ... every handler listed here
    )
```

From `eclipse/main/di/providers/repositories.py`:

```python
class RepositoryProvider(Provider):
    scope = Scope.REQUEST

    user_repository = provide(
        SQLALchemyUserRepository, provides=UserRepository
    )
    transaction_manager = provide(
        SQLAlchemyTransactionManager, provides=TransactionManager
    )
```

### 4.3 Composition root location

The composition root lives in `main/`. The `main/entrypoints/web/factory.py`
calls `create_container()` and passes it to `setup_dishka(container, app)`.

From `eclipse/main/entrypoints/web/factory.py`:

```python
def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Eclipse",
        root_path=settings.app.root_path,
        debug=settings.app.debug,
        lifespan=lifespan,
    )
    configure_service_logging("web")
    container = create_container()
    setup_http_routes(app)
    map_exc_handlers(app)
    setup_dishka(container, app)
    setup_http_middlewares(app, settings=settings)
    return app
```

---

## 5. Dataclass Conventions

### Commands, Queries, Results, Config, Value Objects (immutable):

```python
@dataclass(frozen=True, kw_only=True, slots=True)
```

### Entities (mutable, identity-based):

```python
@dataclass(eq=False, kw_only=True)
```

### Application common DTOs:

```python
@dataclass(frozen=True, kw_only=True, slots=True)
class ListResult[T]:
    items: list[T] = field(default_factory=list)
    count: int = 0
```

### No bare `@dataclass` without explicit flags.

---

## 6. Error Handling

Two error hierarchies, one per layer:

### Domain errors (`domain/errors.py`):

```python
class DomainError(Exception):
    message: str


class StatementAlreadyCachedError(DomainError):
    message = "Statement is already cached"
```

### Application errors (`application/errors.py`):

```python
class ApplicationError(Exception):
    message: str


class ExtractionFailedError(ApplicationError):
    message = "Extraction failed"


class SpendCapExceededError(ApplicationError):
    message = "Spend cap exceeded"


class NotABankStatementError(ApplicationError):
    message = "Document is not a bank statement"
```

### Exception handler mapping (presentation layer):

From `eclipse/presentation/api/http/common/exc_handlers.py`:

```python
def _error_handler(
    request: Request,
    exc: ApplicationError | DomainError,
    status_code: int,
) -> JSONResponse:
    return JSONResponse({"detail": exc.message}, status_code=status_code)


def map_exc_handlers(app: FastAPI) -> None:
    app.add_exception_handler(
        NotABankStatementError,
        partial(_error_handler, status_code=422),
    )
    app.add_exception_handler(
        SpendCapExceededError,
        partial(_error_handler, status_code=429),
    )
    app.add_exception_handler(Exception, _internal_error_handler)
```

---

## 7. Specifications Pattern

Composable query predicates from the domain layer. The infrastructure
layer translates them to storage-specific filters.

### Base (domain/common/specification.py):

```python
from abc import ABC, abstractmethod


class Specification[T](ABC):
    __slots__ = ()

    @abstractmethod
    def is_satisfied_by(self, candidate: T) -> bool:
        raise NotImplementedError

    def __and__(self, other: Specification[T]) -> AndSpecification[T]:
        return AndSpecification(left=self, right=other)

    def __or__(self, other: Specification[T]) -> OrSpecification[T]:
        return OrSpecification(self, other)

    def __invert__(self) -> NotSpecification[T]:
        return NotSpecification(self)

    @classmethod
    def all_of(cls, specs: Iterable[Specification[T]]) -> Specification[T] | None:
        items = list(specs)
        if not items:
            return None
        return reduce(and_, items)
```

### Concrete specifications (domain/specifications/):

```python
class UserHasPersonnelNumber(Specification[User]):
    __slots__ = ("personnel_number",)

    def __init__(self, personnel_number: str) -> None:
        self.personnel_number = personnel_number

    def is_satisfied_by(self, candidate: User) -> bool:
        return candidate.personnel_number == self.personnel_number
```

### Usage in handlers:

```python
user = await self._user_repository.get(
    UserHasPersonnelNumber(command.personnel_number)
)

existing = await self._session_repository.get(
    SessionBelongsToUser(user.oid) & SessionIsActive()
)
```

For dobs, specifications apply to cache lookups:
`CacheEntryHasKey(key)`, `CacheEntryIsReconciled()`, etc.
They are optional -- only add if there is a genuine query composition need.

---

## 8. Repository Pattern

Repositories are Protocol interfaces in `application/ports/`. They expose
a spec-based `get()` API.

From `eclipse/application/ports/repositories/user_repository.py`:

```python
class UserRepository(Protocol):
    @abstractmethod
    async def get(
        self, spec: Specification[User], *, for_update: bool = False
    ) -> User | None:
        raise NotImplementedError

    @abstractmethod
    def add(self, user: User) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get_list(
        self,
        spec: Specification[User] | None,
        *,
        limit: int | None = None,
        offset: int | None = None,
        sort_by: SortBy = SortBy.CREATED_AT,
        sort_order: SortOrder = SortOrder.DESC,
    ) -> ListResult[User]:
        raise NotImplementedError
```

For dobs, the cache and audit ports use a simpler shape:

```python
class StatementCachePort(Protocol):
    @abstractmethod
    async def get(self, key: str) -> Statement | None:
        raise NotImplementedError

    @abstractmethod
    async def put(self, key: str, statement: Statement) -> None:
        raise NotImplementedError

    @abstractmethod
    async def delete(self, key: str) -> bool:
        raise NotImplementedError
```

---

## 9. Logging Pattern

`structlog` with JSON rendering. The reference configures it in
`main/config/logging.py`.

From `eclipse/main/config/logging.py`:

```python
import structlog


def configure_logging(settings: LoggingSettings) -> None:
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]

    renderer = structlog.processors.JSONRenderer(
        sort_keys=True, ensure_ascii=False,
    )

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return cast(
        structlog.stdlib.BoundLogger, structlog.get_logger(name)
    )
```

Usage in modules:

```python
logger = get_logger(__name__)
logger.info("App created", extra={"app_version": app.version})
```

For dobs: replace all `logging.getLogger(__name__)` calls with
`get_logger(__name__)` from a shared `main/config/logging.py`.

---

## 10. Test Patterns

### pytest-asyncio configuration (from `eclipse/pyproject.toml`):

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "session"
asyncio_default_test_loop_scope = "session"
markers = [
  "integration: smoke/integration tests requiring external services",
]
```

### Test layout mirrors source layout:

```
tests/
├── domain/
│   ├── test_reconcile.py
│   ├── test_anomaly.py
│   ├── test_forensic.py
│   └── test_continuity.py
├── application/
│   ├── test_pipeline_mocked.py   (handler tests with mock ports)
│   └── test_extract_hybrid.py
├── infrastructure/
│   ├── test_cache_redis.py
│   ├── test_audit.py
│   ├── test_ingest.py
│   └── test_vendor_lookup.py
└── presentation/
    └── test_api_smoke.py
```

### polyfactory for test data generation

The reference lists `polyfactory>=2.0.0` in dev deps. Use it to generate
test entities without hand-crafting every field.

### Fixture scope

- Session-scoped: event loop, database engine, app factory.
- Function-scoped: individual test data, mock backends.

---

## 11. Configuration via pydantic-settings

From `eclipse/main/config/settings.py`:

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    name: str = "eclipse"
    env: str = "local"
    debug: bool = True
    log_level: str = "INFO"
    host: str = "127.0.0.1"
    port: int = 8000


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        env_nested_delimiter="_",
        extra="ignore",
    )

    app: AppSettings = AppSettings()
    # ... nested settings groups


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
```

For dobs, the nested groups will be:

```python
class LLMSettings(BaseSettings):
    backend: str = "anthropic"
    tier: str = "balanced"
    anthropic_api_key: str = ""
    ollama_host: str = "http://localhost:11434"

class CacheSettings(BaseSettings):
    url: str = "sqlite:out/cache.db"

class AuditSettings(BaseSettings):
    db_path: str = "out/audit.db"

class ExtractionSettings(BaseSettings):
    parallel_workers: int = 2
    spend_cap_usd: float | None = None
    enrich_default: bool = False
    ocr_mode: str = "auto"
```

---

## 12. CQRS: Commands Write, Queries Read

### Commands

Commands represent intents that **change state** or **produce side effects**.
File naming: `<verb>_<noun>.py` under `application/commands/<subdomain>/`.

Each file contains:
- `<Verb><Noun>Command` — frozen dataclass, the input.
- `<Verb><Noun>Result` — frozen dataclass, the output (optional, `None` for void).
- `<Verb><Noun>Handler` — class with `async def __call__(self, command) -> result`.

### Queries

Queries represent **read-only** operations. File naming:
`get_<noun>.py` under `application/queries/`.

Each file contains:
- `Get<Noun>Query` — frozen dataclass, the input (optional for parameterless).
- `Get<Noun>Result` / `<Noun>ListItem` — frozen dataclass, the output DTO.
- `Get<Noun>Handler` — class with `async def __call__(self, query) -> result`.

### Presentation layer maps between HTTP schemas and commands/queries

From `eclipse/presentation/api/http/v1/auth/router.py`:

```python
@router.post("/login", status_code=status.HTTP_201_CREATED)
async def login(
    body: LoginRequest,
    handler: FromDishka[LoginHandler],
) -> None:
    await handler(
        LoginCommand(
            personnel_number=body.personnel_number,
            password=body.password,
        )
    )
```

The router constructs the Command from the HTTP request body, calls the
handler, and maps the result to an HTTP response schema. No business logic
in the router.

---

## Style Rules (Non-Negotiable)

1. **No comments in Python files.** Module-level docstrings only when the
   reference codebase uses them (it does not -- eclipse has zero docstrings
   and zero comments in production code).

2. **No `import *`.** Explicit imports only.

3. **No bare `except`.** Always catch specific exception types.

4. **Type annotations on all public signatures.** Return type `-> None`
   explicitly.

5. **Private attributes prefixed with `_`.** All injected deps stored as
   `self._name`.

6. **Import order:** stdlib, third-party, first-party (dobs). Enforced by
   ruff isort.

7. **Line length:** 120 characters (matches eclipse's ruff config).

8. **One handler per file.** Never put two handlers in the same module.

9. **Ports never import infrastructure.** The dependency arrow points
   inward: infrastructure depends on application, application depends on
   domain. Never the reverse.

10. **Domain layer has zero third-party imports** (except stdlib). Pydantic
    schemas live in the application layer or presentation layer, not domain.
