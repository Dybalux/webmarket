# 📦 MongoDB Atlas → Local (mongodump + restore)

Instructivo para bajar un dump de MongoDB Atlas y restaurarlo en el Mongo
local que corre en Docker. Útil para trabajar con datos reales sin depender
de la red ni gastar el cluster de Atlas.

---

## 📋 Estado actual (junio 2026)

Este proyecto usa los siguientes datos como referencia:

| Concepto | Valor |
|----------|-------|
| Cluster Atlas | `bdBebidas` (`bdbebidas.lo70i9s.mongodb.net`) |
| DB origen en Atlas | `bebidas_db` |
| DB destino en local | `webmarket_prod` |
| Usuario Mongo | `dybalux` |
| Colecciones (10) | `users`, `products`, `orders`, `combos`, `carts`, `refresh_tokens`, `pricing_settings`, `system_settings`, `payment_settings`, `shipping_settings` |

---

## 1. Verificar acceso a Atlas

### 1.1 — IP whitelist

El sandbox que ejecuta los comandos debe estar autorizado en
**Atlas → Security → Network Access**.

IP actual del sandbox: `186.12.188.160` (cambia entre sesiones).

Para autorizar la IP actual:

```bash
curl -s https://api.ipify.org
# te devuelve la IP pública
```

En Atlas UI: **Security → Network Access → + Add IP Address** → pegar la IP
con `/32` (ej: `186.12.188.160/32`) o usar `0.0.0.0/0` para abrir al mundo
(NO recomendado para producción, OK para dev).

### 1.2 — Credenciales

Si no recordás el password del usuario Mongo, **resetealo**:

1. **Security → Database & Network Access** (NO Project Identity & Access,
   esa es la pantalla equivocada)
2. Tab **"Database Users"**
3. Click en el usuario (`dybalux`)
4. **Edit → Edit Password → Autogenerate Secure Password** (botón negro)
5. **Copialo inmediatamente** (Atlas te lo muestra una sola vez)
6. **Update User** (abajo de la página — si no hacés esto, no se guarda)
7. Esperá ~20 segundos para que Atlas propague el cambio

---

## 2. Listar colecciones del dump (opcional pero recomendado)

Sirve para confirmar que el password anda y para ver qué hay antes de bajar.

```bash
export ATLAS_PASSWORD="<tu_password_aqui>"
ATLAS_URI="mongodb+srv://dybalux:${ATLAS_PASSWORD}@bdbebidas.lo70i9s.mongodb.net/bebidas_db"

docker run --rm mongo:latest mongosh "${ATLAS_URI}" --quiet --eval '
  print("Conectado a: " + db.getName());
  print("Colecciones:");
  db.getCollectionNames().forEach(function(collName) {
    var count = db.getCollection(collName).countDocuments();
    print("  - " + collName + ": " + count + " docs");
  });
'
```

---

## 3. Ejecutar `mongodump` desde Docker

**No hace falta instalar nada** — todo se hace con `docker run` usando la
imagen `mongo:latest` que ya tenés.

```bash
export ATLAS_PASSWORD="<tu_password_aqui>"
ATLAS_URI="mongodb+srv://dybalux:${ATLAS_PASSWORD}@bdbebidas.lo70i9s.mongodb.net/bebidas_db"

# Directorio de destino en el host
DUMP_DIR="/tmp/opencode/mongo-atlas-dump"
rm -rf "$DUMP_DIR"
mkdir -p "$DUMP_DIR"
chmod 777 "$DUMP_DIR"  # IMPORTANTE: el container mongo corre como root

docker run --rm \
  -v "${DUMP_DIR}:/dump" \
  mongo:latest \
  mongodump --uri "${ATLAS_URI}" --db bebidas_db --out /dump
```

Output esperado:

```
writing `bebidas_db.users` to `/dump/bebidas_db/users.bson`
done dumping `bebidas_db.users` (12 documents)
... (etc, una línea por colección)
```

---

## 4. Restaurar en Mongo local con rename de DB

**Concepto clave**: `--nsFrom` y `--nsTo` permiten renombrar la DB al
restaurar. Útil cuando querés preservar el nombre original de Atlas
(`bebidas_db`) pero usar un nombre más descriptivo en local
(`webmarket_prod`).

```bash
DUMP_DIR="/tmp/opencode/mongo-atlas-dump"

docker run --rm \
  -v "${DUMP_DIR}:/dump" \
  --network webmarket-network \
  mongo:latest \
  mongorestore \
    --host mongo:27017 \
    --username admin \
    --password "miContraseñaSecreta" \
    --authenticationDatabase admin \
    --nsFrom "bebidas_db.*" \
    --nsTo "webmarket_prod.*" \
    --drop \
    /dump
```

Flags importantes:

- `--host mongo:27017` — usa el container `mongo` de docker-compose
- `--username admin --password ...` — credenciales del Mongo local
  (definidas en `docker-compose.yaml` y `.env`)
- `--nsFrom "bebidas_db.*" --nsTo "webmarket_prod.*"` — renombra DB y todas
  sus colecciones
- `--drop` — dropea la colección destino si ya existe (evita duplicados)
- `/dump` — directorio donde está el dump (montado desde el host)

Output esperado:

```
finished restoring `webmarket_prod.users` (12 documents, 0 failures)
... (etc)
186 document(s) restored successfully. 0 document(s) failed to restore.
```

---

## 5. Apuntar el backend a la nueva DB

Editar el `.env` del backend:

```bash
# /home/dybalux/Escritorio_Dev/webmarket/.env
DATABASE_NAME=webmarket_prod  # antes era webmarket_dev
```

Reiniciar el backend con la nueva env var (si lo corrés en Docker, hay que
pasarle la var explícitamente porque el `.env` solo se lee si está montado):

```bash
docker stop webmarket-backend
docker run -d --rm --name webmarket-backend \
  --network webmarket-network \
  -p 8000:8000 \
  -v /home/dybalux/Escritorio_Dev/webmarket:/app \
  -w /app \
  -e DATABASE_URL=mongodb://admin:miContraseñaSecreta@mongo:27017 \
  -e DATABASE_NAME=webmarket_prod \
  -e REDIS_URL=redis://redis:6379 \
  -e FRONTEND_URL=http://localhost:3000 \
  -e JWT_SECRET=local-dev-secret \
  python:3.13.7-slim \
  sh -c "pip install --no-cache-dir -q -r requirements.txt && python3 main.py"
```

⚠️ **Si el backend se reinicia con el mismo `requirements.txt` instalado
de antes**, podés saltarte el `pip install`:

```bash
docker run -d --rm --name webmarket-backend \
  ... (mismas env vars)
  python:3.13.7-slim \
  sh -c "python3 main.py"
```

---

## 6. Validar end-to-end

### 6.1 — Counts en Mongo local

```bash
docker exec mongo mongosh --quiet -u admin -p "miContraseñaSecreta" \
  --authenticationDatabase admin --eval '
    db.getSiblingDB("webmarket_prod").getCollectionNames().forEach(function(collName) {
      var count = db.getSiblingDB("webmarket_prod").getCollection(collName).countDocuments();
      print("  - " + collName + ": " + count + " docs");
    });
  '
```

### 6.2 — Backend ve los datos

```bash
curl -sL http://localhost:8000/products | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'products: {d[\"meta\"][\"total\"]}')
"
```

### 6.3 — Vía tunnel (frontend en Vercel)

```bash
curl -sL https://api.altotrago.com/products | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'products: {d[\"meta\"][\"total\"]}')
"
```

### 6.4 — Comparar counts Atlas vs Local

Los números deberían coincidir. Si no coinciden, reverificar el dump o el
restore.

---

## 7. Troubleshooting

### "permission denied" al escribir en `/dump`

El container mongo corre como root, pero el host directory tiene permisos
del usuario actual. Fix:

```bash
chmod 777 /tmp/opencode/mongo-atlas-dump
# o usar otro dir sin permisos restrictivos
```

### "bad auth: authentication failed"

- El password es incorrecto → resetealo en Atlas UI
- Atlas todavía no propagó el cambio → esperá 20-30 segundos
- El usuario no existe en la DB que pusiste en el URI

### "connection refused" al restaurar

- El container `mongo` no está corriendo: `docker ps | grep mongo`
- Estás en una red distinta: usá `--network webmarket-network`

### "Database not found" después de restaurar

- Verificá que usaste `--nsFrom`/`--nsTo` correctos
- Listá las DBs en local: `db.adminCommand("listDatabases")`

### `/products` o `/combos` devuelven menos docs que la DB

Es **comportamiento normal** — los endpoints aplican filtros como
`active: true` o paginación default. Para ver TODOS los docs, consultar
directo a Mongo con mongosh.

---

# 📋 TL;DR

```bash
# Setup (1 sola vez)
export ATLAS_PASSWORD="<password>"
ATLAS_URI="mongodb+srv://dybalux:${ATLAS_PASSWORD}@bdbebidas.lo70i9s.mongodb.net/bebidas_db"
DUMP_DIR="/tmp/opencode/mongo-atlas-dump"
chmod 777 /tmp/opencode && mkdir -p "$DUMP_DIR" && chmod 777 "$DUMP_DIR"

# Dump
docker run --rm -v "${DUMP_DIR}:/dump" mongo:latest \
  mongodump --uri "${ATLAS_URI}" --db bebidas_db --out /dump

# Restore (rename a webmarket_prod)
docker run --rm -v "${DUMP_DIR}:/dump" --network webmarket-network \
  mongo:latest mongorestore \
    --host mongo:27017 -u admin -p "miContraseñaSecreta" --authenticationDatabase admin \
    --nsFrom "bebidas_db.*" --nsTo "webmarket_prod.*" --drop /dump

# Apuntar backend a la nueva DB
echo "DATABASE_NAME=webmarket_prod" >> .env
# (reiniciar container de backend con la env var)
```
