# Design: Audit Logging & Idempotency

## Technical Approach

Two PRs. **PR-1 (audit)**: resurrect the dead `audit` logger via dual async helpers — `log_audit` (routers), `log_audit_ctx` (services) — sharing one `_emit()` for byte-identical JSON; `AuditContext` plumbed router→service. **PR-2 (idempotency)**: Redis `SET NX` guard in new `utils/idempotency.py` on `POST /orders` and `POST /payments/create-preference/{order_id}`; per-user keys, 24h TTL, cached-JSON replay. Helpers async (conftest already patches `log_audit` with `AsyncMock`); stock-mutation audit is fire-and-forget.

## Architecture Decisions

### ADR-1: Dual-helper pattern
**Choice**: `log_audit(event, request, details)` + `log_audit_ctx(event, *, ctx, details)`, both delegating to `_emit()`.
**Alternatives**: one function with `Request | AuditContext` union.
**Rationale**: services must not import `Request` (layer boundary); one `_emit()` guarantees identical JSON (S1.2).

### ADR-2: AuditContext dataclass
**Choice**: frozen dataclass `(client_ip, method, path)`; built via `from_request()`; services take optional `audit_ctx=None`.
**Alternatives**: three raw strings; mandatory ctx.
**Rationale**: one object survives signature growth; the default keeps all 109 existing tests untouched; `None` → `"N/A"` (S1.3).

### ADR-3: Fire-and-forget for stock mutations
**Choice**: `asyncio.create_task` for stock audit (order decrement + admin inventory ops); plain `await` elsewhere.
**Alternatives**: all fire-and-forget; all awaited.
**Rationale**: stock paths are p95-sensitive (≤2ms, S1.4); rare auth/admin events keep deterministic test ordering. Helpers never raise — orphan tasks are safe.

### ADR-4: Redis SET NX vs DB unique constraint
**Choice**: two-phase Redis — `SET key IN_FLIGHT NX EX 86400` → run handler → `SET key <json> KEEPTTL`.
**Alternatives**: Mongo unique index on `(user_id, key)` + response collection.
**Rationale**: Redis already in stack; TTL free; replay is one `GET`. Idempotency is a cache concern, not a data constraint.

### ADR-5: Fail-open when Redis is down
**Choice**: catch `RedisError` → WARNING → run handler without idempotency.
**Alternatives**: fail-closed (503).
**Rationale**: availability beats exactly-once (R5/S2.5); a Redis blip must not stop sales.

### ADR-6: Server-side fallback key
**Choice**: missing header → `sha256(user_id | endpoint | canonical_json(payload))` as `idem:{user_id}:{endpoint}:fb:{hash}`.
**Alternatives**: reject 400; proceed keyless.
**Rationale**: R4 mandates graceful degradation; payload hashing gives legacy clients double-click protection without cross-cart collisions. Invalid header → 400 pre-logic (S2.3).

## Component Diagram

```
POST /orders | POST /payments/create-preference
     ▼
router: extract Idempotency-Key ─invalid─▶ 400
     │ build AuditContext from Request
     ▼
idempotency.get_or_set(redis, key, producer)
   │           │
 NX miss    NX hit ▶ GET cached JSON ▶ 200 (no re-execute)
   ▼
service(ctx) ─▶ awaited audit (ORDER_CREATED …)
           └─▶ create_task audit (STOCK_DECREMENTED)
   ▼
SET key response KEEPTTL ▶ 201
```

## Data Flow

- **Login ✓/✗**: router `await log_audit(event, request, {"username"})` → `_emit` → `json.dumps` (single line, injection-safe, S1.5) → `audit` stdout.
- **Order creation**: header → UUID validate → `SET NX` → miss → `create_order(ctx)` (`ORDER_CREATED` awaited; `STOCK_DECREMENTED` via `create_task`) → response cached `KEEPTTL` → 201. Replay → cached JSON 200; no DB work, no second decrement (S2.2).
- **Admin role change**: `await log_audit(ADMIN_ROLE_CHANGED, request, {admin_id, target_user, from_role, to_role})` post-update.

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `audit_logger.py` | Modify | +12 enum values; `AuditContext`; `log_audit` → async, `request \| None`; new `log_audit_ctx`; `_emit` try/except (never raises) |
| `utils/idempotency.py` | Create | `validate_key` (UUID-4 else 400); `get_or_set` (SET NX; `IN_FLIGHT` → 409); `fallback_key`; fail-open WARNING |
| `routers/auth.py` | Modify | `Request` param + audit: login ✓/✗, register, forgot, reset |
| `routers/admin.py` | Modify | `ADMIN_ROLE_CHANGED` in `update_user_role` |
| `routers/products.py` | Modify | `ADMIN_PRODUCT_CREATED` / `_UPDATED` |
| `routers/payments.py` | Modify | `PAYMENT_WEBHOOK_RECEIVED`; idempotency + ctx on create-preference |
| `routers/orders.py` | Modify | header + `get_or_set` on `POST /`; build ctx |
| `services/payments.py` | Modify | ctx kwarg; `PAYMENT_FAILED`, `MP_PREFERENCE_CREATED`, `SIGNATURE_INVALID` |
| `services/orders.py` | Modify | ctx kwarg; `ORDER_CREATED`, `ORDER_CANCELLED`, `ORDER_STATUS_CHANGED`, `STOCK_RESTORED` |
| `services/orders_helpers.py` | Modify | `create_task(STOCK_DECREMENTED)` in `_decrement_stock_batch` |
| `services/inventory.py` | Modify | `update_stock` → DECREMENTED/RESTORED by delta sign; `add_stock` → RESTORED; `create_task` |
| `tests/conftest.py` | Modify | silence fixture += `log_audit_ctx`; `FakeRedis.set(nx=, ex=, keepttl=)` |
| `tests/unit/test_audit_logger.py` | Create | JSON shape, request=None, ctx parity, forging |
| `tests/unit/test_idempotency.py` | Create | UUID 400, replay, fallback, fail-open, cross-user |
| `tests/integration/test_audit_wiring.py` | Create | AsyncMock asserts for all 19 call points |
| `tests/integration/test_idempotency_replay.py` | Create | duplicate `POST /orders` → one order, one decrement |

## Interfaces / Contracts

```python
@dataclass(frozen=True)
class AuditContext:
    client_ip: str = "N/A"; method: str = "N/A"; path: str = "N/A"
    @classmethod
    def from_request(cls, request: Request) -> "AuditContext": ...

async def log_audit(event: AuditEvent, request: Request | None, details: dict) -> None
async def log_audit_ctx(event: AuditEvent, *, ctx: AuditContext | None, details: dict) -> None

# key: idem:{user_id}:{endpoint}:{uuid | fb:hash}
async def get_or_set(redis, key: str, ttl: int, producer: Callable[[], Awaitable[T]]) -> tuple[T, bool]
def validate_key(header: str | None) -> str | None   # invalid → 400
def fallback_key(user_id: str, endpoint: str, payload: BaseModel) -> str
```

## Sequence Diagrams

**Order creation with idempotency**
```
Client→Router: POST /orders (Idempotency-Key: uuid)
Router→Redis: SET idem:u:orders:uuid IN_FLIGHT NX EX 86400
alt NX ok
  Router→Svc: create_order(ctx)
  Svc→Audit: await ORDER_CREATED │ create_task STOCK_DECREMENTED
  Router→Redis: SET key <json> KEEPTTL → Client: 201
else hit
  Router→Redis: GET cached json (IN_FLIGHT → 409) → Client: 200
```

**Login failure audit trail**
```
Client→Router: POST /token (bad password)
Router→Security: record_failure(redis, username)
Router→Audit: await log_audit(USER_LOGIN_FAILED, request, {username})
Audit→stdout: single JSON line → Router→Client: 401
```

**Admin stock update (fire-and-forget audit)**
```
Admin→Router: PUT /inventory/{id}/stock → Svc: update_stock(ctx)
Svc→Mongo: $set stock
Svc→Loop: create_task(log_audit_ctx(STOCK_*)) ─▶ stdout
Svc→Router→Admin: 200 (audit never awaited)
```

## Error Handling

| Failure | Behavior |
|---------|----------|
| Audit write throws | swallowed in `_emit`; fallback `logging.warning`; never propagates (invariant 1) |
| Redis unreachable | WARNING; handler runs without idempotency (S2.5) |
| Invalid UUID header | 400 before business logic (S2.3, invariant 4) |
| Duplicate while `IN_FLIGHT` | 409 `idempotency_in_progress` |
| Orphaned `IN_FLIGHT` (crash) | TTL expires ≤24h; retry with new key |

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | helper JSON/None/forging; key validation, fallback, fail-open | FakeRedis, caplog |
| Integration | audit wiring per endpoint; replay = identical body, one decrement | test_client + AsyncMock |

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary.

## Migration / Rollout

No migration. PR-1 audit (~380 LOC), PR-2 idempotency (~300 LOC) — chained, each ≤400. Revert = merge-revert.

## Open Questions

- [ ] `ADMIN_USER_DELETED`: no user-delete endpoint exists — enum added, wiring deferred pending endpoint or spec amendment.
- [ ] Spec R4 lists "bad signature" under auth; design emits `SIGNATURE_INVALID` once from `services/payments` (R5), preserving invariant 3.
