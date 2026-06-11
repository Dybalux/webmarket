# 🚇 Cloudflare Tunnel — Instructivo de setup local

Exponer el backend `webmarket` (que corre en tu PC) a internet para que el
frontend en Vercel pueda consumirlo.

---

## 📋 Estado actual (junio 2026)

Este proyecto usa **named tunnel con dominio custom delegado a Cloudflare**.

- **Tunnel name**: `webmarket-api`
- **Tunnel ID**: `501953f7-d9f1-4753-ae2d-00f35ac0f454`
- **Hostname público**: `https://api.altotrago.com`
- **Service backend**: `http://localhost:8000` (FastAPI + uvicorn)
- **DNS delegation**: NS records apuntan a `laila.ns.cloudflare.com` y `roman.ns.cloudflare.com`

Hay 2 modos para arrancar desde cero:

| Modo | URL | Persistente | Requiere |
|------|-----|-------------|----------|
| **A) Quick tunnel** | `https://xxxx.trycloudflare.com` (cambia cada vez) | ❌ | Nada, solo `cloudflared` |
| **B) Named tunnel** | `https://api.altotrago.com` (fija) | ✅ | Dominio delegado a Cloudflare DNS |

**Recomendación**: usá named tunnel (B) para desarrollo serio. Quick tunnel solo para probar cosas rápido.

---

## 1. Instalar `cloudflared`

### Arch / CachyOS (binario oficial)

```bash
curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
  -o ~/.local/bin/cloudflared
chmod +x ~/.local/bin/cloudflared
~/.local/bin/cloudflared --version
```

### macOS

```bash
brew install cloudflared
```

### Debian / Ubuntu

```bash
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \
  | sudo gpg --dearmor -o /usr/share/keyrings/cloudflare.gpg
echo "deb [signed-by=/usr/share/keyrings/cloudflare.gpg] https://pkg.cloudflare.com/cloudflared $(lsb_release -cs) main" \
  | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt update && sudo apt install cloudflared
```

---

## 2. Levantar Mongo + Redis + Backend

Desde la raíz del repo `webmarket`:

```bash
# 2.1 — Levantar Mongo y Redis
docker compose up -d mongo_bebidas redis_bebidas

# 2.2 — Verificar que están corriendo
docker compose ps

# 2.3 — Levantar el backend en otra terminal
cd /home/dybalux/Escritorio_Dev/webmarket
python3 main.py
# o con uvicorn directo:
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### Verificar que el backend responde

```bash
curl http://localhost:8000/docs
# esperado: HTML de la documentación Swagger
```

---

## 3. Modo A: Quick tunnel (sin cuenta Cloudflare)

Para probar algo rápido sin setup.

```bash
cloudflared tunnel --url http://localhost:8000
```

Vas a ver:

```
+-----------------------------------------------------------+
|  Your quick Tunnel has been created! Visit it at:         |
|  https://xxxx-xxxx-xxxx.trycloudflare.com                 |
+-----------------------------------------------------------+
```

⚠️ La URL **muere** cuando cerrás `cloudflared`. Cada vez que la levantás de
cero, la URL cambia y hay que actualizar Vercel.

---

## 4. Modo B: Named tunnel con dominio custom (RECOMENDADO)

URL fija tipo `https://api.altotrago.com`. Requiere que el dominio esté delegado
a Cloudflare DNS.

### 4.1 — Verificar delegación DNS

```bash
dig NS altotrago.com +short @1.1.1.1
# esperado: laila.ns.cloudflare.com., roman.ns.cloudflare.com. (o similar)
```

Si no apunta a Cloudflare, seguí el instructivo de delegación en la sección 5.

### 4.2 — Crear API Token con permisos de Account + DNS

En **dash.cloudflare.com → My Profile → API Tokens → Create Custom Token**:

| Campo | Valor |
|-------|-------|
| Token name | `webmarket-tunnel-management` |
| Permissions row 1 | `Account / Cloudflare Tunnel / Edit` |
| Permissions row 2 | `Zone / DNS / Edit` |
| Account Resources | `Include / Specific account / <tu cuenta>` |
| Zone Resources | `Include / Specific zone / altotrago.com` (recomendado) o `All zones` |

> **Nota**: el template pre-armado "Edit Cloudflare Tunnel" también sirve, pero
> verificar que tenga `Zone / DNS / Edit` en la sección Permissions.

### 4.3 — Crear el tunnel vía API

```bash
export CLOUDFLARE_API_TOKEN="cfut_xxxxxxxxxxxxx"
ACCOUNT_ID="<id de tu cuenta — visible en dash.cloudflare.com → Workers → Overview → Account ID>"

curl -s -X POST "https://api.cloudflare.com/client/v4/accounts/${ACCOUNT_ID}/cfd_tunnel" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "webmarket-api",
    "config_src": "cloudflare"
  }' | python3 -m json.tool
```

De la respuesta guardar:

- `result.id` → **TUNNEL_ID** (UUID)
- `result.credentials_file.TunnelSecret` → el secret

### 4.4 — Crear el archivo de credenciales

```bash
mkdir -p ~/.cloudflared

cat > ~/.cloudflared/${TUNNEL_ID}.json <<EOF
{
  "AccountTag": "${ACCOUNT_ID}",
  "TunnelSecret": "<TunnelSecret de la respuesta>",
  "TunnelID": "${TUNNEL_ID}"
}
EOF

chmod 600 ~/.cloudflared/${TUNNEL_ID}.json
```

### 4.5 — Crear el config.yml con ingress

```bash
cat > ~/.cloudflared/config.yml <<EOF
tunnel: ${TUNNEL_ID}
credentials-file: /home/TU_USUARIO/.cloudflared/${TUNNEL_ID}.json

ingress:
  - hostname: api.altotrago.com
    service: http://localhost:8000
  - service: http_status:404
EOF

chmod 600 ~/.cloudflared/config.yml
```

### 4.6 — Registrar la config en Cloudflare (ingress + route DNS)

```bash
curl -s -X PUT "https://api.cloudflare.com/client/v4/accounts/${ACCOUNT_ID}/cfd_tunnel/${TUNNEL_ID}/configurations" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "config": {
      "ingress": [
        {
          "hostname": "api.altotrago.com",
          "service": "http://localhost:8000"
        },
        {
          "service": "http_status:404"
        }
      ]
    }
  }'
```

### 4.7 — Crear el record CNAME en la zona DNS

**Importante**: este paso se hace **además** del route DNS del tunnel. El
record CNAME es lo que hace que `api.altotrago.com` resuelva al tunnel.

```bash
ZONE_ID="<id de la zona — visible en dash.cloudflare.com → altotrago.com → Overview → zone_id en la URL>"
CNAME_TARGET="${TUNNEL_ID}.cfargotunnel.com"

curl -s -X POST "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"type\": \"CNAME\",
    \"name\": \"api.altotrago.com\",
    \"content\": \"${CNAME_TARGET}\",
    \"proxied\": true,
    \"comment\": \"Webmarket API backend tunnel\"
  }"
```

Verificar que se creó:

```bash
curl -s "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records?name=api.altotrago.com" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN"
```

### 4.8 — Correr el tunnel

```bash
cloudflared tunnel --config ~/.cloudflared/config.yml --no-autoupdate run ${TUNNEL_ID}
```

Deberías ver:

```
INF Registered tunnel connection connIndex=0 ... location=eze04 protocol=quic
INF Updated to new configuration config="..." version=1
```

### 4.9 — (Opcional) Instalar como servicio systemd

Para que arranque solo al boot y se mantenga corriendo:

```bash
sudo cloudflared service install
sudo systemctl enable cloudflared
sudo systemctl start cloudflared
sudo journalctl -u cloudflared -f   # ver logs
```

---

## 5. Configurar Vercel

En **vercel.com/dashboard → escabi-frontend → Settings → Environment Variables**:

| Key | Value |
|-----|-------|
| `VITE_API_URL` | `https://api.altotrago.com` (sin barra final) |

**Save** → ir a **Deployments** → click en el último → **Redeploy**.

> Recordá: Vite embebe las envs `VITE_*` en el bundle JS en **build time**.
> Cambiar la env var y NO redeployar no hace nada.

---

## 6. Validar end-to-end

### Desde la terminal

```bash
# Backend responde directo (sin tunnel)
curl http://localhost:8000/system-status

# Tunnel responde vía dominio custom
curl https://api.altotrago.com/system-status
# esperado: {"maintenance_mode":false,"message":""}

# Vercel está apuntando al tunnel
curl -s https://altotrago.com/assets/$(curl -s https://altotrago.com | grep -oE 'assets/index-[A-Za-z0-9_-]+\.js' | head -1) | grep -oE "https?://api\.altotrago\.com"
# esperado: https://api.altotrago.com
```

### Desde el navegador

1. Abrí `https://altotrago.com` (o `https://escabi-frontend.vercel.app`)
2. DevTools → Network
3. Hacé una request que toque el backend (login, listar productos, etc.)
4. La URL de la request tiene que empezar con `https://api.altotrago.com`
5. La respuesta tiene que ser 200, no CORS error, no 502

---

## 7. Troubleshooting

### "Tunnel connection: failed" en logs

- Verificar que el backend en `localhost:8000` esté corriendo
- Verificar que el `credentials-file` en `config.yml` apunte a un JSON válido
- Verificar que `TunnelID` en el JSON coincida con el del dashboard

### "502 Bad Gateway" en `api.altotrago.com`

- El tunnel está corriendo pero no llega al backend
- Verificar que el `service` en ingress sea `http://localhost:8000`
- Verificar que el puerto 8000 esté abierto localmente: `ss -tlnp | grep 8000`

### "404 DEPLOYMENT_NOT_FOUND" con headers de Vercel

**Causa**: la request a `api.altotrago.com` está yendo a un deployment de
Vercel en lugar del tunnel. Esto pasa si:

1. El record CNAME en Cloudflare no se creó (paso 4.7) → la wildcard
   `*.altotrago.com` toma precedencia y puede apuntar a Vercel.
2. El subdominio está configurado como Production Domain en un proyecto de
   Vercel → hay que sacarlo de ahí (Vercel → Project → Settings → Domains).

**Fix**: verificar que el CNAME exista en la zona DNS y que NO esté
configurado en Vercel.

### "DNS propagation: el tunnel funciona a veces sí, a veces no"

Acabás de crear el record CNAME. Esperá 1-5 minutos para que propague
globalmente. Podés verificar con:

```bash
dig A api.altotrago.com +short @1.1.1.1
dig A api.altotrago.com +short @8.8.8.8
# ambos deberían devolver IPs de Cloudflare (104.x, 172.67.x)
```

### El tunnel funciona pero Vercel sigue con la URL vieja

Vite embebe las env vars en build time. **Tenés que redeployar el frontend
explícitamente** después de cambiar la env var.

---

## 8. Apagar todo

```bash
# Si está corriendo como systemd
sudo systemctl stop cloudflared

# Si lo corriste manualmente
pkill -f "cloudflared tunnel"

# Bajar Mongo y Redis
docker compose down
```

---

# 🌐 Instructivo: delegar `altotrago.com` a Cloudflare DNS

Para que el named tunnel funcione, el dominio tiene que estar delegado a
Cloudflare como nameserver autoritativo.

## Paso 1 — Crear cuenta en Cloudflare

1. Ir a https://dash.cloudflare.com/sign-up
2. Registrarse con email y password
3. Plan Free alcanza y sobra

## Paso 2 — Agregar el dominio

1. En el dashboard, click **"Add a site"**
2. Escribir `altotrago.com`
3. Cloudflare escanea los DNS records existentes (~30s)
4. Elegir plan **Free** ($0)
5. **NO cerrar** esta pantalla — necesitás los nameservers

## Paso 3 — Cambiar nameservers en tu registrar

Cloudflare te da dos nameservers tipo:

```
<random>.ns.cloudflare.com
<random>.ns.cloudflare.com
```

Los nombres exactos los ves en el dashboard. Ahora vas al lugar donde
compraste `altotrago.com` y cambiás los nameservers.

### GoDaddy

1. My Products → Domains → `altotrago.com` → **DNS**
2. Cambiar de "Default" a "Custom"
3. Pegar los dos nameservers
4. Save

### Namecheap

1. Domain List → `altotrago.com` → **Manage**
2. Nameservers → "Custom DNS"
3. Pegar los dos
4. Save

### Hostinger (el que usa altotrago.com)

1. Panel → Domains → `altotrago.com` → **DNS / Nameservers**
2. Cambiar a "Custom nameservers"
3. Pegar los dos
4. Save

## Paso 4 — Esperar la delegación

- Tarda entre 5 minutos y 48 horas
- En el dashboard de Cloudflare el estado pasa de "Pending" a "Active"
- Te llega email cuando se completa
- Verificar manualmente:

```bash
dig NS altotrago.com +short
# esperado: <random>.ns.cloudflare.com. <random>.ns.cloudflare.com.
```

## Paso 5 — Volver al paso 4.2 de este instructivo

Una vez que el dominio esté "Active" en Cloudflare, seguí desde la sección
4.2 (crear API token) de este mismo instructivo.

---

# 📋 TL;DR

| Paso | Acción | Tiempo |
|------|--------|--------|
| 1 | Instalar `cloudflared` | 1 min |
| 2 | Levantar Mongo + Redis + backend | 2 min |
| 3A | (Quick) `cloudflared tunnel --url http://localhost:8000` | 30s |
| 3B | (Named) Delegar dominio + crear tunnel + config + CNAME | 30 min primera vez, 5 min siguientes |
| 4 | Vercel: `VITE_API_URL=https://api.altotrago.com` + redeploy | 2 min |
| 5 | Validar end-to-end con curl + navegador | 2 min |

---

# 🔐 Tokens y credenciales — DÓNDE GUARDAR

| Qué | Dónde | Permisos |
|-----|-------|----------|
| API Token `CLOUDFLARE_API_TOKEN` | `~/.cloudflared-private/tokens.env` (chmod 600) | Account: Tunnel:Edit + Zone: DNS: Edit (en `altotrago.com`) |
| Tunnel credentials JSON | `~/.cloudflared/<TUNNEL_ID>.json` (chmod 600) | (autogenerado al crear el tunnel) |
| Config YAML | `~/.cloudflared/config.yml` (chmod 600) | (declarativo, podés commitearlo sin secrets) |

**NUNCA commitear tokens ni credentials JSON al repo.**

---

# 📚 Referencias

- [Cloudflare Tunnel docs](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/)
- [Named tunnel setup](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/tunnel-guide/)
- [API: create tunnel](https://developers.cloudflare.com/api/operations/cloudflare-tunnel-create-a-cloudflare-tunnel)
- [Vite env vars](https://vitejs.dev/guide/env-and-mode.html)
