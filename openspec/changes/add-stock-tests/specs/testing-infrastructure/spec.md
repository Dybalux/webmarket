# Testing Infrastructure Specification

## Purpose

Bootstrap the project's test infrastructure. The webmarket codebase has zero test infrastructure today: no `pytest`, no test dependencies, no `conftest.py`, no `pytest.ini`. This spec defines the minimum plumbing — dev dependencies, pytest configuration, shared fixtures, and a test app pattern — required before any stock-control test can run. It also defines the coverage contract for the project.

## Requirements

### Requirement: Dev Dependency Manifest

The project MUST ship a `requirements-dev.txt` file that pins every test-time dependency so a fresh virtual environment can install the test toolchain with a single command.

The `requirements-dev.txt` MUST include: `pytest`, `pytest-asyncio`, `httpx`, `mongomock-motor`, `pytest-cov`, `freezegun`, `pytest-mock`. `requirements.txt` SHOULD reference `requirements-dev.txt` via `-r requirements-dev.txt` so a default install includes dev tooling.

#### Scenario: Fresh install enables test runs

- GIVEN a clean Python 3.13 virtualenv with no packages installed
- WHEN the developer runs `pip install -r requirements-dev.txt`
- THEN `pytest` is on `PATH` AND `import mongomock_motor` succeeds
- AND `httpx`, `pytest-asyncio`, `pytest-cov`, `freezegun`, `pytest-mock` are importable

#### Scenario: Production install remains lean

- GIVEN a deployment environment that only needs runtime deps
- WHEN the deployer installs `requirements-prod.txt` only
- THEN pytest, mongomock-motor, and httpx are NOT pulled in

### Requirement: Pytest Configuration

A `pytest.ini` (or `[tool.pytest.ini_options]` in `pyproject.toml`) MUST exist at the project root and MUST set `asyncio_mode = auto`, `testpaths = tests`, and a `pythonpath` entry that lets tests import `routers`, `stock_helpers`, `models`, `database` without manual `sys.path` manipulation.

The config SHOULD register markers `unit`, `integration`, `endpoint` so tests can be filtered per PR layer.

#### Scenario: Async tests run without decorators

- GIVEN a test file under `tests/` containing an `async def test_*` function with no `@pytest.mark.asyncio` decorator
- WHEN `pytest` is invoked from the project root
- THEN the test is collected AND executed by pytest-asyncio
- AND no `PytestUnconfiguredException` is raised

#### Scenario: Marker-based test selection

- GIVEN tests across all three layers
- WHEN the developer runs `pytest -m unit` or `pytest -m integration`
- THEN only tests carrying the matching marker are executed

### Requirement: Shared Test Fixtures (conftest.py)

A top-level `conftest.py` MUST expose the fixtures required by every test in the project: `mock_db` (a fresh `AsyncMongoMockClient` per test), `reset_db_singleton` (re-points `database.db` to the mock), `override_db_deps` (overrides `get_database` and `get_collection` FastAPI dependencies), `auth_user_dep` and `auth_admin_dep` (overrides for the three auth dependencies), and `client` (a `fastapi.testclient.TestClient` bound to a minimal app that bypasses `MaintenanceModeMiddleware` and the production `lifespan`).

The conftest MUST also mock `audit_logger` and `email_service` to prevent real side effects.

#### Scenario: Database singleton is reset per test

- GIVEN test A inserts a product into the mock DB
- WHEN test B starts and calls `reset_db_singleton`
- THEN test B sees an empty products collection
- AND `database.db` points to a new `AsyncMongoMockClient` instance

#### Scenario: TestClient bypasses MaintenanceModeMiddleware

- GIVEN the production `main.py` registers `MaintenanceModeMiddleware` that calls `get_database()` on every request
- WHEN a test uses the `client` fixture
- THEN no real MongoDB connection is attempted
- AND no "connection refused" error appears in test output

#### Scenario: Auth dependencies are overridable per test

- GIVEN a test that needs an admin user to call `PUT /inventory/{id}/stock`
- WHEN the test applies the `auth_admin_dep` override
- THEN the endpoint sees the mocked admin user
- AND the test does not need a real JWT or session

#### Scenario: Email and audit side effects are silenced

- GIVEN a router that calls `email_service.send_email` and `audit_logger.log` on every order
- WHEN the test client fires a request
- THEN no real email is sent
- AND no real audit record is written to any database

### Requirement: Test App Isolation

The `client` fixture MUST build a **minimal** FastAPI app instance that mounts only the routers under test. It MUST NOT import `main.py` (which would trigger the real `lifespan` and middleware chain). Each test file MAY register a different subset of routers.

The minimal app MUST disable `MaintenanceModeMiddleware` and MUST NOT call `lifespan` startup/shutdown hooks that connect to MongoDB or Redis.

#### Scenario: TestClient app is independent of main.py

- GIVEN the production `main.py` includes `app.add_middleware(MaintenanceModeMiddleware)`
- WHEN a test imports `conftest.client` and sends a request
- THEN `MaintenanceModeMiddleware` is NOT in the ASGI middleware stack
- AND the test does not trigger MongoDB or Redis connection logic

### Requirement: Coverage Configuration

`pytest.ini` (or `pyproject.toml`) MUST configure `pytest-cov` with a `[run]` source set covering `routers/`, `stock_helpers.py`, `models.py`, `database.py`, and `pricing_helpers.py`. The minimum line-coverage threshold for the `add-stock-tests` change is `0%` (current state); future changes MUST raise the bar.

The coverage report MUST exclude `tests/`, `scripts/`, `__pycache__`, and `.venv`.

#### Scenario: Coverage report is generated

- GIVEN the project has any test files
- WHEN `pytest --cov` is invoked
- THEN a coverage report is printed
- AND the source files listed above appear in the report

### Requirement: Test File Organization

Tests MUST live under a top-level `tests/` directory. The directory MUST contain `__init__.py` (empty), `conftest.py` (shared fixtures, may be re-exported from root `conftest.py`), and one file per module under test. Test file names MUST follow `test_<module>.py`.

Unit tests for `stock_helpers.py` MUST live in `tests/test_stock_helpers.py`. Integration tests for the inventory router MUST live in `tests/test_inventory.py`. Endpoint tests for the orders router MUST live in `tests/test_orders_stock.py`. Endpoint tests for the cart router MUST live in `tests/test_cart_stock.py`. Admin stats tests MUST live in `tests/test_admin_stats.py`.

#### Scenario: Test discovery is deterministic

- GIVEN a developer runs `pytest` from the project root with no arguments
- WHEN pytest collects tests
- THEN every file matching `tests/test_*.py` is collected
- AND no file outside `tests/` is treated as a test
