"""Migrate monetary float fields to Decimal128 in MongoDB.

ADR-6: Idempotent one-shot migration that converts BSON double (float) monetary
fields to bson.Decimal128. Safe to re-run — already-migrated documents are
skipped via BSON type check before write.

Usage:
    # Upgrade (float → Decimal128)
    python scripts/migrate_floats_to_decimal128.py

    # Downgrade (Decimal128 → float) — rollback path
    python scripts/migrate_floats_to_decimal128.py --downgrade

    # Dry-run (show what would change without writing)
    python scripts/migrate_floats_to_decimal128.py --dry-run

    # Target specific collection
    python scripts/migrate_floats_to_decimal128.py --collection products

Requirements:
    - Must be run with the app's virtualenv active
    - Requires DATABASE_URL and DATABASE_NAME in .env
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Add project root to path so we can import config and database modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from bson import Decimal128, SON
from pymongo import ASCENDING
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from config import settings


# ---------------------------------------------------------------------------
# Monetary field definitions per collection
# ---------------------------------------------------------------------------
# Each entry: (collection_name, [list of monetary field paths])
# Nested paths use dot notation (e.g., "items.price_at_purchase").

MONETARY_FIELDS: Dict[str, List[str]] = {
    "products": [
        "price",
        "net_price",
    ],
    "orders": [
        "total_amount",
        "shipping_cost",
        "items.price_at_purchase",
    ],
    "combos": [
        "price",
        "items.price",  # if combo items carry embedded prices
    ],
    "shipping_settings": [
        "central_zone_price",
        "remote_zone_price",
        "pickup_price",
    ],
    "dynamic_pricing_settings": [
        "multiplier",
    ],
    "carts": [],  # carts reference product IDs, not prices directly
}


def _get_nested(doc: Dict[str, Any], path: str) -> Any:
    """Retrieve a nested value by dot-separated path. Returns _SENTINEL if missing."""
    parts = path.split(".")
    current = doc
    for part in parts:
        if not isinstance(current, dict):
            return _SENTINEL
        current = current.get(part, _SENTINEL)
    return current


def _set_nested(doc: Dict[str, Any], path: str, value: Any) -> None:
    """Set a nested value by dot-separated path (creates intermediate dicts)."""
    parts = path.split(".")
    current = doc
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


_SENTINEL = object()


def _convert_value(value: Any, direction: str) -> Any:
    """Convert a single value between float and Decimal128.

    Args:
        value: The current BSON value.
        direction: "upgrade" (float → Decimal128) or "downgrade" (Decimal128 → float).

    Returns:
        The converted value, or _SENTINEL if no conversion needed.
    """
    if direction == "upgrade":
        if isinstance(value, float):
            try:
                return Decimal128(str(value))
            except (InvalidOperation, ValueError):
                return _SENTINEL
        # Already Decimal128 or non-numeric — skip
        return _SENTINEL

    elif direction == "downgrade":
        if isinstance(value, Decimal128):
            try:
                return float(str(value))
            except (ValueError, OverflowError):
                return _SENTINEL
        # Already float or non-numeric — skip
        return _SENTINEL

    return _SENTINEL


def _process_list_items(items: list, field_name: str, direction: str) -> Tuple[list, int]:
    """Process a list of sub-documents, converting a specific field in each.

    Returns (new_list, converted_count).
    """
    new_items = []
    converted = 0
    for item in items:
        if isinstance(item, dict) and field_name in item:
            new_val = _convert_value(item[field_name], direction)
            if new_val is not _SENTINEL:
                item = {**item, field_name: new_val}
                converted += 1
        new_items.append(item)
    return new_items, converted


async def migrate_collection(
    db: AsyncIOMotorDatabase,
    collection_name: str,
    fields: List[str],
    direction: str,
    dry_run: bool = False,
) -> Tuple[int, int]:
    """Migrate monetary fields in a single collection.

    Args:
        db: The database instance.
        collection_name: Name of the collection to migrate.
        fields: List of monetary field paths (dot notation for nested).
        direction: "upgrade" or "downgrade".
        dry_run: If True, count changes without writing.

    Returns:
        (documents_scanned, documents_modified)
    """
    if not fields:
        return 0, 0

    collection = db[collection_name]

    # Separate top-level fields from nested list fields (e.g., "items.price_at_purchase")
    top_level_fields = [f for f in fields if "." not in f]
    nested_fields = [f for f in fields if "." in f]

    # Build a query that matches documents with at least one field needing conversion
    # For upgrade: field exists and is BSON double (type 1)
    # For downgrade: field exists and is Decimal128 (type 19)
    bson_type = 1 if direction == "upgrade" else 19

    or_conditions = []
    for field in top_level_fields:
        or_conditions.append({field: {"$type": bson_type}})
    for field in nested_fields:
        # For nested fields like "items.price_at_purchase", match if any array
        # element has the field as the target type
        parent = field.split(".")[0]
        child = ".".join(field.split(".")[1:])
        or_conditions.append({f"{parent}.{child}": {"$type": bson_type}})

    if not or_conditions:
        return 0, 0

    query = {"$or": or_conditions}

    scanned = 0
    modified = 0

    cursor = collection.find(query)
    async for doc in cursor:
        scanned += 1
        doc_id = doc["_id"]
        update_set: Dict[str, Any] = {}
        needs_update = False

        # Process top-level fields
        for field in top_level_fields:
            if field not in doc:
                continue
            new_val = _convert_value(doc[field], direction)
            if new_val is not _SENTINEL:
                update_set[field] = new_val
                needs_update = True

        # Process nested list fields (e.g., items.price_at_purchase)
        for field in nested_fields:
            parts = field.split(".")
            if len(parts) != 2:
                continue  # Only support one level of nesting for now
            parent_key, child_key = parts
            parent_val = doc.get(parent_key)
            if isinstance(parent_val, list):
                new_list, count = _process_list_items(parent_val, child_key, direction)
                if count > 0:
                    update_set[parent_key] = new_list
                    needs_update = True

        if needs_update and not dry_run:
            await collection.update_one(
                {"_id": doc_id},
                {"$set": update_set},
            )
            modified += 1
        elif needs_update:
            modified += 1  # Count would-be modifications in dry-run

    return scanned, modified


async def run_migration(direction: str = "upgrade", dry_run: bool = False, target_collection: str | None = None) -> None:
    """Run the full migration across all configured collections.

    Args:
        direction: "upgrade" (float → Decimal128) or "downgrade" (Decimal128 → float).
        dry_run: If True, show changes without writing.
        target_collection: If set, only migrate this collection.
    """
    client = AsyncIOMotorClient(
        settings.DATABASE_URL,
        serverSelectionTimeoutMS=5000,
    )
    db = client[settings.DATABASE_NAME]

    # Verify connectivity
    try:
        await client.admin.command("ping")
    except Exception as exc:
        print(f"❌ Cannot connect to MongoDB: {exc}")
        sys.exit(1)

    label = "UPGRADE (float → Decimal128)" if direction == "upgrade" else "DOWNGRADE (Decimal128 → float)"
    mode_label = "DRY-RUN" if dry_run else "LIVE"

    print(f"\n{'='*60}")
    print(f"🔧 Decimal Migration — {label}")
    print(f"   Mode: {mode_label}")
    print(f"   Database: {settings.DATABASE_NAME}")
    print(f"{'='*60}\n")

    total_scanned = 0
    total_modified = 0

    collections_to_process = (
        {target_collection: MONETARY_FIELDS.get(target_collection, [])}
        if target_collection
        else MONETARY_FIELDS
    )

    for coll_name, fields in collections_to_process.items():
        if not fields:
            print(f"  ⏭️  {coll_name}: no monetary fields configured, skipping")
            continue

        scanned, modified = await migrate_collection(db, coll_name, fields, direction, dry_run)
        total_scanned += scanned
        total_modified += modified

        status = "would modify" if dry_run else "modified"
        if modified > 0:
            print(f"  ✅ {coll_name}: scanned {scanned}, {status} {modified}")
        else:
            print(f"  ⏭️  {coll_name}: scanned {scanned}, already migrated")

    print(f"\n{'='*60}")
    print(f"📊 Migration Summary")
    print(f"   Documents scanned:  {total_scanned}")
    action = "would be modified" if dry_run else "modified"
    print(f"   Documents {action}: {total_modified}")
    if dry_run and total_modified > 0:
        print(f"\n💡 Run without --dry-run to apply changes.")
    elif total_modified == 0:
        print(f"\n✅ All documents already in target format — nothing to do.")
    print(f"{'='*60}\n")

    client.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate monetary float fields to Decimal128 (or rollback)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Upgrade all collections (float → Decimal128)
  python scripts/migrate_floats_to_decimal128.py

  # Dry-run to see what would change
  python scripts/migrate_floats_to_decimal128.py --dry-run

  # Downgrade (rollback: Decimal128 → float)
  python scripts/migrate_floats_to_decimal128.py --downgrade

  # Target a single collection
  python scripts/migrate_floats_to_decimal128.py --collection products
        """,
    )

    parser.add_argument(
        "--downgrade",
        action="store_true",
        help="Reverse the migration: convert Decimal128 back to float",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing to the database",
    )

    parser.add_argument(
        "--collection",
        type=str,
        choices=list(MONETARY_FIELDS.keys()),
        help="Target a specific collection instead of all",
    )

    args = parser.parse_args()
    direction = "downgrade" if args.downgrade else "upgrade"

    asyncio.run(run_migration(
        direction=direction,
        dry_run=args.dry_run,
        target_collection=args.collection,
    ))


if __name__ == "__main__":
    main()
