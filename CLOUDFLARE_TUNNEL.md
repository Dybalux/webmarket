# 🚇 Cloudflare Tunnel — Instructivo de setup local

Exponer el backend `webmarket` (que corre en tu PC) a internet para que el
frontend en Vercel pueda consumirlo. Reemplaza a ngrok (que ya está en el
`docker-compose.yaml` pero no es la solución definitiva).

Hay dos modos:

- **Quick tunnel** (modo A): URL aleatoria `*.trycloudflare.com`, cambia cada
  vez que reiniciás. Sirve para probar. No requiere cuenta en Cloudflare.
- **Named tunnel** (modo B): URL fija tipo `https://api.altotrago.com`.
  Requiere delegar `altotrago.com` a Cloudflare DNS. Ver instructivo al final.

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

### Verificar

```bash
cloudflared --version
# esperado: cloudflared version 2026.x.x (built ...)
```

---

## 2. Levantar Mongo + Redis + Backend

Desde la raíz del repo `webmarket`:

```bash
# 2.1 — Levantar Mongo y Redis (NO usar el servicio ngrok del compose)
docker compose up -d mongo_bebidas redis_bebidas

# 2.2 — Verificar que están corriendo
docker compose ps
# esperado: mongo y redis en estado "running"

# 2.3 — Instalar dependencias Python (primera vez)
python3 -m pip install -r requirements.txt -r requirements-dev.txt

# 2.4 — Levantar el backend en otra terminal
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

Si ves JSON de error o "connection refused", revisá que Mongo y Redis estén
corriendo y que `.env` tenga las credenciales correctas.

---

## 3. Quick tunnel (modo A — sin cuenta Cloudflare)

En una **tercera terminal**:

```bash
cloudflared tunnel --url http://localhost:8000
```

Vas a ver algo así:

```
+-----------------------------------------------------------+
|  Your quick Tunnel has been created! Visit it at:         |
|  https://xxxx-xxxx-xxxx.trycloudflare.com                 |
+-----------------------------------------------------------+
```

**Copiá esa URL.** Es la que va a ir en `VITE_API_URL` de Vercel.

### Verificar

```bash
# En otra terminal, contra la URL del tunnel
curl https://xxxx-xxxx-xxxx.trycloudflare.com/docs
# esperado: HTML de Swagger, igual que en localhost
```

⚠️ **Cuidado**: la URL **muere** cuando cerrás `cloudflared`. Cada vez que
levantás el backend de cero, la URL cambia y hay que actualizar Vercel.

---

## 4. Configurar el frontend en Vercel

1. Ir a https://vercel.com → proyecto `escabi-frontend` → **Settings** → **Environment Variables**
2. Agregar / editar:
   - **Key**: `VITE_API_URL`
   - **Value**: la URL del quick tunnel del paso 3 (sin barra final)
   - **Environment**: Production (y Preview si querés)
3. **Redeploy** el proyecto (Deployments → ... → Redeploy) para que tome la nueva env var.

⚠️ Recordá: cada vez que la URL del quick tunnel cambie, tenés que repetir este paso.

---

## 5. Validar end-to-end

1. Abrí `https://escabi-frontend.vercel.app` (o tu dominio custom)
2. Abrí DevTools → Network
3. Hacé una request que toque el backend (login, listar productos, lo que sea)
4. La URL de la request tiene que empezar con la URL del quick tunnel
5. La respuesta tiene que ser 200, no CORS error, no 502

Si ves error de CORS, agregá el dominio del quick tunnel a `origins` en
`webmarket/main.py` (no es necesario — `trycloudflare.com` ya tiene HTTPS
válido y tu CORS permite Vercel — pero si cambia algo, ahí está el lugar).

---

## 6. Apagar todo

```bash
# Cerrá las terminales donde corren uvicorn y cloudflared (Ctrl+C)
docker compose down  # baja Mongo y Redis
```

---

# 🌐 Instructivo: delegar `altotrago.com` a Cloudflare DNS

Esto es lo que necesitás hacer para pasar del **quick tunnel** (URL que cambia)
a un **named tunnel** (URL fija tipo `https://api.altotrago.com`).

## Paso 1 — Crear cuenta en Cloudflare

1. Ir a https://dash.cloudflare.com/sign-up
2. Registrarse con email y password
3. Plan Free alcanza y sobra para esto

## Paso 2 — Agregar el dominio

1. En el dashboard, click **"Add a site"**
2. Escribir `altotrago.com` (sin www, sin https://)
3. Cloudflare escanea los DNS records existentes (tarda ~30s)
4. Elegir plan **Free** ($0)
5. **NO cerrar** esta pantalla — necesitás los nameservers en el paso siguiente

## Paso 3 — Cambiar nameservers en tu registrar

Cloudflare te va a dar dos nameservers tipo:

```
anna.ns.cloudflare.com
bob.ns.cloudflare.com
```

Los nombres exactos los ves en el dashboard. Ahora tenés que ir al lugar
donde compraste `altotrago.com` y cambiar los nameservers:

### Si compraste en GoDaddy

1. Login → My Products → Domains → `altotrago.com` → **DNS** (o **Nameservers**)
2. Cambiar de "Default" a "Custom"
3. Pegar los dos nameservers de Cloudflare
4. Save

### Si compraste en Namecheap

1. Login → Domain List → `altotrago.com` → **Manage**
2. Pestaña **Nameservers** → cambiar de "Namecheap BasicDNS" a "Custom DNS"
3. Pegar los dos nameservers
4. Save (icono verde)

### Si compraste en otro registrar

El procedimiento es el mismo: buscá la opción "Nameservers" o "Custom DNS"
para el dominio y reemplazá los actuales por los de Cloudflare.

## Paso 4 — Esperar la delegación

- Cloudflare chequea cada pocos minutos. A veces tarda **5 minutos**, a veces
  **hasta 48 horas** (depende del registrar).
- En el dashboard de Cloudflare vas a ver el estado pasar de "Pending" a
  "Active". Te llega un email cuando se completa.
- Verificar manualmente:
  ```bash
  dig NS altotrago.com +short
  # esperado: anna.ns.cloudflare.com. bob.ns.cloudflare.com.
  ```

## Paso 5 — Crear el named tunnel

Una vez que Cloudflare diga "Active":

```bash
# Login (abre el navegador una vez)
cloudflared tunnel login

# Crear el tunnel
cloudflared tunnel create webmarket-api
# te devuelve un UUID y un path a credentials-file (json)

# Crear el subdominio (api.altotrago.com → tunnel)
cloudflared tunnel route dns webmarket-api api.altotrago.com
```

## Paso 6 — Configurar el tunnel

Crear `~/.cloudflared/config.yml`:

```yaml
tunnel: webmarket-api
credentials-file: /home/TU_USUARIO/.cloudflared/<UUID>.json

ingress:
  - hostname: api.altotrago.com
    service: http://localhost:8000
  - service: http_status:404
```

## Paso 7 — Correr el tunnel como servicio

```bash
# Instalar como servicio del sistema (systemd)
sudo cloudflared service install
sudo systemctl enable cloudflared
sudo systemctl start cloudflared

# Ver logs
sudo journalctl -u cloudflared -f
```

## Paso 8 — Actualizar Vercel

Cambiar `VITE_API_URL` de la URL del quick tunnel a:

```
https://api.altotrago.com
```

Redeploy. **Esta URL es permanente** — no cambia nunca más.

---

# 📋 TL;DR

| Paso | Acción | Tiempo |
|------|--------|--------|
| 1 | Instalar `cloudflared` | 1 min |
| 2 | Levantar Mongo + Redis + backend | 2 min |
| 3 | Quick tunnel: `cloudflared tunnel --url http://localhost:8000` | 30s |
| 4 | Copiar URL → Vercel env var `VITE_API_URL` → redeploy | 2 min |
| 5 | Validar end-to-end desde Vercel | 2 min |
| 6 | (Futuro) Delegar `altotrago.com` → named tunnel fijo | 30 min + espera DNS |
