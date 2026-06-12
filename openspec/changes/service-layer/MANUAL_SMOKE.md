# Manual Smoke Test — Service Layer

**Purpose**: Verify that the 6 key API endpoints return byte-identical responses before and after the service-layer refactor. This is a planning artifact — not a runnable script. An operator (or the `sdd-archive` phase) should use these curl commands against a running server with seeded test data.

**Prerequisites**:
- Server running on `http://localhost:8000` (or equivalent)
- Authenticated admin and user tokens available
- MongoDB seeded with at least one product, one combo, one user with cart items, and one order

---

## 1. POST /orders

**Request**:
```bash
curl -X POST http://localhost:8000/orders \
  -H "Authorization: Bearer <user_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "shipping_address": "Calle Falsa 123",
    "shipping_zone": "central"
  }'
```

**Expected Response**:
- Status: `201 Created`
- Body: `Order` JSON object with fields: `_id`, `user_id`, `items`, `total_amount`, `status`, `shipping_address`, `shipping_zone`, `shipping_cost`, `payment_method`, `created_at`, `updated_at`
- Stock decremented for each item
- Cart cleared

**Notes**: This endpoint exercises the full order creation flow including stock `$gte` guard, combo resolution, dynamic pricing, shipping calculation, and email notification.

---

## 2. POST /cart/add

**Request**:
```bash
curl -X POST http://localhost:8000/cart/add \
  -H "Authorization: Bearer <user_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "product_id": "<product_id>",
    "quantity": 1
  }'
```

**Expected Response**:
- Status: `200 OK`
- Body: `Cart` JSON object with `user_id` and `items` array
- Each item includes `product_id`, `quantity`, `is_combo`, and price enrichment

**Notes**: Tests stock validation, combo detection, and price enrichment via PricingService.

---

## 3. GET /products

**Request**:
```bash
curl http://localhost:8000/products
```

**Expected Response**:
- Status: `200 OK`
- Body: Array of `Product` objects (zero-stock items excluded by default)
- Dynamic pricing applied if active

**Notes**: Verifies that PricingService's `get_adjusted_price` is correctly applied to product listings.

---

## 4. GET /orders/me

**Request**:
```bash
curl http://localhost:8000/orders/me \
  -H "Authorization: Bearer <user_token>"
```

**Expected Response**:
- Status: `200 OK`
- Body: Array of `Order` objects for the authenticated user, sorted newest first

**Notes**: Paginated by default (limit=50, skip=0).

---

## 5. PUT /orders/admin/{id}/status

**Request**:
```bash
curl -X PUT http://localhost:8000/orders/admin/<order_id>/status \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "new_status": "CONFIRMED"
  }'
```

**Expected Response**:
- Status: `200 OK`
- Body: Updated `Order` object with `status: "CONFIRMED"`

**Notes**: If `new_status` is `CANCELLED` or `REFUNDED`, stock is restored for all items (inside the if-block, per indentation fix from `add-stock-tests`).

---

## 6. POST /payments/webhook

**Request**:
```bash
curl -X POST http://localhost:8000/payments/webhook \
  -H "Content-Type: application/json" \
  -H "x-signature: <hmac_signature>" \
  -H "x-request-id: <request_id>" \
  -d '{
    "type": "payment",
    "data": {
      "id": "<payment_id>"
    }
  }'
```

**Expected Response**:
- Status: `200 OK`
- Body: `{"status": "ok"}` (or empty body depending on current implementation)

**Notes**: This endpoint validates the Mercado Pago HMAC-SHA256 signature, checks idempotency, updates order status, and always returns 200 to the webhook caller. Manual testing requires valid Mercado Pago credentials or signature bypass in test mode.

---

## 7. POST /products (admin — create)

**Request**:
```bash
curl -X POST http://localhost:8000/products \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Cerveza Patagonia 1L",
    "description": "Cerveza artesanal Patagonia",
    "price": 2500.0,
    "category": "Cerveza",
    "stock": 30,
    "image_url": "https://example.com/patagonia.jpg",
    "abv": 5.2,
    "volume_ml": 1000,
    "origin": "Argentina",
    "active": true
  }'
```

**Expected Response**:
- Status: `201 Created`
- Body: `AdminProduct` JSON object with all fields including `_id`, `net_price`
- Duplicate name → `409 Conflict` with `"El nombre del producto ya existe."`
- Insert failure → `500 Internal Server Error` with `"No se pudo crear el producto."`

**Notes**: Admin-only endpoint. Uses ProductsService.create_product. Validates unique product name via DuplicateProductNameError.

---

### GET /products (public — list)

Already documented in Section 3. Now routed through ProductsService.list_products.

---

### GET /products/{id} (public — single)

**Request**:
```bash
curl http://localhost:8000/products/<product_id>
```

**Expected Response**:
- Status: `200 OK`
- Body: `Product` JSON object with dynamic pricing applied
- Invalid ID → `400 Bad Request` with `"ID de producto inválido."`
- Not found → `404 Not Found` with `"Producto no encontrado."`

**Notes**: Public endpoint. Uses ProductsService.get_product. Filters active=true.

---

### PUT /products/{id} (admin — update)

**Request**:
```bash
curl -X PUT http://localhost:8000/products/<product_id> \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "price": 2800.0,
    "stock": 50
  }'
```

**Expected Response**:
- Status: `200 OK`
- Body: `AdminProduct` JSON with updated fields
- Invalid ID → `400 Bad Request` with `"ID de producto inválido."`
- Not found → `404 Not Found` with `"Producto no encontrado."`
- With `profit_percentage` field: price auto-calculated as `net_price * (1 + profit_pct/100)`

**Notes**: Admin-only endpoint. Uses ProductsService.update_product. Supports partial updates via ProductUpdate model. `profit_percentage` is consumed and removed before DB write.

---

### DELETE /products/{id} (admin — delete)

**Request**:
```bash
curl -X DELETE http://localhost:8000/products/<product_id> \
  -H "Authorization: Bearer <admin_token>"
```

**Expected Response**:
- Status: `204 No Content` (empty body)
- Invalid ID → `400 Bad Request` with `"ID de producto inválido."`
- Not found → `404 Not Found` with `"Producto no encontrado para eliminar."`

**Notes**: Admin-only endpoint. Hard delete from the products collection.

---

### PATCH /products/{id}/toggle-active (admin — toggle)

**Request**:
```bash
curl -X PATCH http://localhost:8000/products/<product_id>/toggle-active \
  -H "Authorization: Bearer <admin_token>"
```

**Expected Response**:
- Status: `200 OK`
- Body: `AdminProduct` JSON with toggled `active` field
- Invalid ID → `400 Bad Request` with `"ID de producto inválido."`
- Not found → `404 Not Found` with `"Producto no encontrado."`

**Notes**: Admin-only endpoint. Soft-delete/restore. Flips the `active` boolean. Uses ProductsService.toggle_product_active.

---

## 8. GET /pricing-settings (public)

**Request**:
```bash
curl http://localhost:8000/pricing-settings
```

**Expected Response**:
- Status: `200 OK`
- Body: `DynamicPricingSettings` JSON with fields: `enabled`, `multiplier`, `start_day`, `end_day`, `start_hour`, `end_hour`, `updated_at`, `updated_by`
- If no settings exist → returns defaults (`enabled=false`, `multiplier=1.0`)
- Unexpected error → `500 Internal Server Error` with `"Error al obtener configuración de precios."`

**Notes**: Public endpoint. Uses PricingService.get_pricing_settings.

---

### GET /admin/pricing-settings (admin)

**Request**:
```bash
curl http://localhost:8000/admin/pricing-settings \
  -H "Authorization: Bearer <admin_token>"
```

**Expected Response**:
- Status: `200 OK`
- Body: `DynamicPricingSettings` JSON (same shape as public)
- Unexpected error → `500 Internal Server Error` with `"Error al obtener configuración de precios."`

**Notes**: Admin endpoint. Same logic as public, guarded by admin auth.

---

### PUT /admin/pricing-settings (admin — update)

**Request**:
```bash
curl -X PUT http://localhost:8000/admin/pricing-settings \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "enabled": true,
    "multiplier": 1.15,
    "start_day": 5,
    "end_day": 7,
    "start_hour": 20,
    "end_hour": 6
  }'
```

**Expected Response**:
- Status: `200 OK`
- Body: `DynamicPricingSettings` JSON with updated fields + `updated_at` timestamp + `updated_by` admin ID
- Creates document if first time; updates existing if already present
- Expected error → `500 Internal Server Error` with `"Error al actualizar configuración de precios."`

**Notes**: Admin endpoint. Uses PricingService.update_pricing_settings. Bridges DynamicPricingUpdate (router input) to DynamicPricingSettings (service).

---

## Verification Procedure

1. Capture response bodies for all 6 endpoints BEFORE the refactor (golden files).
2. Deploy the refactored code.
3. Re-run the same curl commands with identical inputs.
4. Compare response bodies byte-for-byte (`diff golden/actual/`).
5. If any response differs, the refactor broke API 1:1 preservation.

## Status

- **Created**: During sdd-verify phase (2026-06-12)
- **Automated**: No — this is a manual-only verification guide
- **Updated**: PR #5a (2026-06-12) — added sections 7 (Products CRUD, 6 endpoints) and 8 (Pricing settings, 3 endpoints)
- **Updated**: PR #5b-2b (2026-06-12) — added section 9 (Combos CRUD, 6 endpoints)
- **Coverage**: 21 endpoints documented (6 original + 9 PR #5a + 6 PR #5b-2b)

---

## 9. Combos CRUD (6 endpoints)

### GET /combos/ (public — list active)

**Request**:
```bash
curl http://localhost:8000/combos
```

**Expected Response**:
- Status: `200 OK`
- Body: Array of `ComboDetailed` objects (only active combos)
- Each combo includes enriched product info, pricing with dynamic pricing applied, and savings calculation
- Empty DB → `200 OK` with `[]`
- Unexpected error → `500 Internal Server Error` with `"Error al obtener los combos."`

**Notes**: Public endpoint. Uses CombosService.list_active_combos. Fully enriched with `_enrich_combos` (apply_dynamic_pricing=True).

---

### GET /combos/{id} (public — single)

**Request**:
```bash
curl http://localhost:8000/combos/<combo_id>
```

**Expected Response**:
- Status: `200 OK`
- Body: `Combo` JSON with dynamic pricing applied
- Invalid ID → `400 Bad Request` with `"ID de combo inválido."`
- Not found / inactive → `404 Not Found` with `"Combo no encontrado."`
- Unexpected error → `500 Internal Server Error` with `"Error al obtener el combo."`

**Notes**: Public endpoint. Uses CombosService.get_combo_by_id. Only returns active combos. ObjectId validation stays in router.

---

### GET /combos/admin/all (admin — list all)

**Request**:
```bash
curl http://localhost:8000/combos/admin/all \
  -H "Authorization: Bearer <admin_token>"
```

**Expected Response**:
- Status: `200 OK`
- Body: Array of `ComboDetailed` objects (all combos when `include_inactive=true`)
- Query param `include_inactive=false` → only active combos
- Empty list → `200 OK` with `[]`
- Unexpected error → `500 Internal Server Error` with `"Error al obtener la lista de combos."`

**Notes**: Admin endpoint. Uses CombosService.list_all_combos. Base prices only (no dynamic pricing). Enrichment shared with public listing via `_enrich_combos(apply_dynamic_pricing=False)`.

---

### POST /combos/admin (admin — create)

**Request**:
```bash
curl -X POST http://localhost:8000/combos/admin \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Pack Verano",
    "description": "Cerveza + Vino combo",
    "price": 4500.0,
    "image_url": "https://example.com/pack-verano.jpg",
    "items": [
      {"product_id": "<stella_id>", "quantity": 2},
      {"product_id": "<malbec_id>", "quantity": 2}
    ]
  }'
```

**Expected Response**:
- Status: `201 Created`
- Body: `Combo` JSON with `_id`, `name`, `price`, `items`, `active=true`, `created_at`, `updated_at`
- Invalid product ID → `400 Bad Request` with `"ID de producto inválido: <id>"`
- Product not found → `404 Not Found` with `"Producto con ID <id> no encontrado."`
- Insert failure → `500 Internal Server Error` with `"No se pudo crear el combo."`
- Unexpected error → `500 Internal Server Error` with `"Error al crear el combo."`

**Notes**: Admin endpoint. Uses CombosService.create_combo. Validates all referenced product IDs exist before insert.

---

### PUT /combos/admin/{id} (admin — update)

**Request**:
```bash
curl -X PUT http://localhost:8000/combos/admin/<combo_id> \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "price": 4200.0,
    "active": false
  }'
```

**Expected Response**:
- Status: `200 OK`
- Body: `Combo` JSON with updated fields + `updated_at` timestamp
- Invalid combo ID → `400 Bad Request` with `"ID de combo inválido."`
- Combo not found → `404 Not Found` with `"Combo no encontrado."`
- Invalid product ID in items → `400 Bad Request` with `"ID de producto inválido: <id>"`
- Referenced product not found → `404 Not Found` with `"Producto con ID <id> no encontrado."`
- Unexpected error → `500 Internal Server Error` with `"Error al actualizar el combo."`

**Notes**: Admin endpoint. Uses CombosService.update_combo. Partial update via `ComboUpdate` (exclude_unset). Product references are re-validated if `items` field is present.

---

### DELETE /combos/admin/{id} (admin — delete/soft-delete)

**Request**:
```bash
# Soft delete (deactivate)
curl -X DELETE "http://localhost:8000/combos/admin/<combo_id>" \
  -H "Authorization: Bearer <admin_token>"

# Hard delete (permanent)
curl -X DELETE "http://localhost:8000/combos/admin/<combo_id>?permanent=true" \
  -H "Authorization: Bearer <admin_token>"
```

**Expected Response**:
- Soft delete → `200 OK` with `{"message": "Combo desactivado correctamente."}`
- Hard delete → `200 OK` with `{"message": "Combo eliminado permanentemente."}`
- Invalid combo ID → `400 Bad Request` with `"ID de combo inválido."`
- Combo not found → `404 Not Found` with `"Combo no encontrado."`
- Unexpected error → `500 Internal Server Error` with `"Error al eliminar el combo."`

**Notes**: Admin endpoint. Uses CombosService.delete_combo. Default is soft delete (`active=False`). `permanent=true` physically removes the document.
