#!/usr/bin/env bash
# scripts/check_compose_hardening.sh
# Validates docker-compose.yaml hardening: no host ports on DB services,
# pinned image tags, and Redis --requirepass.
set -euo pipefail

COMPOSE_FILE="${1:-docker-compose.yaml}"
FAILURES=0

echo "=== Compose hardening check: $COMPOSE_FILE ==="

# 1. No host ports on mongo_bebidas and redis_bebidas
for svc in mongo_bebidas redis_bebidas; do
    if docker compose -f "$COMPOSE_FILE" config --format json 2>/dev/null \
        | python3 -c "
import sys, json
cfg = json.load(sys.stdin)
svc = cfg.get('services', {}).get('$svc', {})
ports = svc.get('ports', [])
if ports:
    print(f'FAIL: $svc exposes host ports: {ports}', file=sys.stderr)
    sys.exit(1)
print(f'OK: $svc has no host ports')
" 2>&1; then
        :
    else
        echo "FAIL: $svc host port check failed"
        FAILURES=$((FAILURES + 1))
    fi
done

# 2. Pinned image tags (no :latest)
for svc in mongo_bebidas redis_bebidas; do
    IMAGE=$(docker compose -f "$COMPOSE_FILE" config --format json 2>/dev/null \
        | python3 -c "
import sys, json
cfg = json.load(sys.stdin)
print(cfg.get('services', {}).get('$svc', {}).get('image', ''))
")
    if echo "$IMAGE" | grep -qE ':latest$|^[^:]+$'; then
        echo "FAIL: $svc image not pinned: $IMAGE"
        FAILURES=$((FAILURES + 1))
    else
        echo "OK: $svc pinned to $IMAGE"
    fi
done

# 3. Redis --requirepass in command
REDIS_CMD=$(docker compose -f "$COMPOSE_FILE" config --format json 2>/dev/null \
    | python3 -c "
import sys, json
cfg = json.load(sys.stdin)
cmd = cfg.get('services', {}).get('redis_bebidas', {}).get('command', '')
print(cmd)
")
if echo "$REDIS_CMD" | grep -q -- '--requirepass'; then
    echo "OK: redis_bebidas command includes --requirepass"
else
    echo "FAIL: redis_bebidas missing --requirepass in command: $REDIS_CMD"
    FAILURES=$((FAILURES + 1))
fi

echo ""
if [ "$FAILURES" -gt 0 ]; then
    echo "RESULT: $FAILURES check(s) FAILED"
    exit 1
else
    echo "RESULT: all checks passed"
    exit 0
fi
