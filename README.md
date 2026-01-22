# 🍺 EscabiAPI - Sistema de Gestión de Bebidas

API REST completa para e-commerce de bebidas con autenticación JWT, verificación de mayoría de edad, gestión de carritos de compra, sistema de pedidos e integración con Mercado Pago.

[![Python](https://img.shields.io/badge/Python-3.13-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.116.1-009688.svg)](https://fastapi.tiangolo.com/)
[![MongoDB](https://img.shields.io/badge/MongoDB-Atlas-green.svg)](https://www.mongodb.com/)
[![Redis](https://img.shields.io/badge/Redis-Cloud-red.svg)](https://redis.com/)
[![Railway](https://img.shields.io/badge/Deploy-Railway-blueviolet.svg)](https://railway.app/)

---

## 🚀 Demo en Vivo

- **🌐 API Base:** https://web-production-62840.up.railway.app
- **📚 Documentación Interactiva (Swagger):** https://web-production-62840.up.railway.app/docs
- **📖 Documentación Alternativa (ReDoc):** https://web-production-62840.up.railway.app/redoc

---

## 🎯 Características Principales

### Autenticación y Seguridad
- ✅ Sistema de autenticación JWT (JSON Web Tokens)
- ✅ Roles de usuario (Cliente / Administrador)
- ✅ Verificación de mayoría de edad (18+)
- ✅ Rate limiting con Redis (protección contra abuso)
- ✅ Hashing seguro de contraseñas con bcrypt

### Gestión de Productos
- ✅ CRUD completo de productos (bebidas)
- ✅ **Sistema de Combos y Packs promocionales**
- ✅ Categorías: Cerveza, Vinos, Licores, Gaseosas, Combos
- ✅ Filtrado por categoría, precio y búsqueda por texto
- ✅ Cálculo automático de precios (Costo + % Ganancia)
- ✅ Información detallada (ABV, volumen, origen)

### Sistema de Compras
- ✅ Carrito de compras persistente por usuario
- ✅ Gestión de stock en tiempo real
- ✅ Sistema de pedidos con estados
- ✅ Historial de compras
- ✅ Direcciones de envío

### Integración de Pagos
- ✅ Integración completa con Mercado Pago 
- ✅ Generación de preferencias de pago
- ✅ Webhooks para notificaciones en tiempo real
- ✅ Actualización automática de estados de pedido

### Gestión de Inventario
- ✅ Control de stock automático (Individual y Combos)
- ✅ Alertas de bajo inventario
- ✅ Reposición de stock simplificada

### Administración del Sistema
- ✅ Gestión de Roles de Usuario (Admin/Cliente)
- ✅ Modo Mantenimiento con IP permitidas
- ✅ Configuración de Costos de Envío y Retiro en Sucursal
- ✅ Configuración de Redes Sociales y Métodos de Pago

### Auditoría y Logging
- ✅ Sistema de auditoría de eventos críticos
- ✅ Logging estructurado
- ✅ Registro de inicios de sesión y operaciones

---

## 🛠️ Tecnologías Utilizadas

### Backend
- **FastAPI** - Framework web moderno y rápido para Python
- **Python 3.13** - Lenguaje de programación
- **Motor** - Driver asíncrono para MongoDB
- **Pydantic** - Validación de datos
- **python-jose** - Manejo de JWT
- **passlib + bcrypt** - Hashing de contraseñas

### Base de Datos y Caché
- **MongoDB Atlas** - Base de datos NoSQL en la nube
- **Redis Cloud** - Caché y rate limiting

### Servicios Externos
- **Mercado Pago API** - Procesamiento de pagos
- **Railway** - Plataforma de deploy

### Herramientas de Desarrollo
- **Docker & Docker Compose** - Containerización
- **Uvicorn** - Servidor ASGI
- **Git** - Control de versiones

---

## 📚 Documentación de la API

### Módulos Principales

#### 🔐 Autenticación (`/auth`)
- `POST /auth/register` - Registrar nuevo usuario
- `POST /auth/token` - Iniciar sesión (OAuth2)
- `GET /auth/me` - Obtener usuario actual

#### ✅ Verificación de Edad (`/age-verification`)
- `POST /age-verification/verify-age` - Verificar mayoría de edad
- `GET /age-verification/minimum-age` - Obtener edad mínima requerida

#### 🍾 Productos (`/products`)
- `GET /products/` - Listar productos (con filtros)
- `GET /products/{id}` - Obtener producto específico
- `POST /products/` - Crear producto [Admin]
- `PUT /products/{id}` - Actualizar producto [Admin]
- `DELETE /products/{id}` - Eliminar producto [Admin]

#### 🧩 Combos (`/combos`)
- `GET /combos/` - Listar combos activos
- `GET /combos/{id}` - Detalles de combo
- `POST /combos/` - Crear combo [Admin]
- `PUT /combos/{id}` - Editar combo [Admin]
- `DELETE /combos/{id}` - Eliminar combo [Admin]

#### 🛒 Carrito (`/cart`)
- `GET /cart/` - Ver carrito actual
- `POST /cart/add` - Agregar producto al carrito
- `PUT /cart/update` - Actualizar cantidad de producto
- `DELETE /cart/remove/{product_id}` - Eliminar producto del carrito
- `DELETE /cart/clear` - Vaciar carrito

#### 📦 Pedidos (`/orders`)
- `POST /orders/` - Crear pedido desde carrito
- `GET /orders/me` - Ver mis pedidos
- `GET /orders/{id}` - Ver detalles de un pedido
- `PUT /orders/admin/{id}/status` - Actualizar estado [Admin]

#### 💳 Pagos (`/payments`)
- `POST /payments/create-preference/{order_id}` - Crear preferencia de Mercado Pago
- `POST /payments/webhook` - Webhook de Mercado Pago

#### 📊 Inventario (`/inventory`) [Admin]
- `PUT /inventory/{product_id}/stock` - Establecer stock
- `PUT /inventory/{product_id}/stock/add` - Reponer stock
- `GET /inventory/alerts` - Ver alertas de bajo stock

#### ⚙️ Configuración (`/admin` & Settings)
- `GET /admin/users` - Gestión de usuarios y roles
- `GET/PUT /admin/system-status` - Modo mantenimiento
- `GET/PUT /admin/shipping-settings` - Configuración de envíos
- `GET/PUT /admin/payment-settings` - Redes sociales y pagos

---

## 🎮 Guía de Uso Rápido

### 1. Registrar un Usuario

**Endpoint:** `POST /auth/register`

```json
{
  "username": "juanperez",
  "email": "juan@example.com",
  "password": "MiPassword123!",
  "birth_date": "1995-06-15T00:00:00.000Z"
}
```

### 2. Iniciar Sesión

**Endpoint:** `POST /auth/token`

**Form Data:**
- username: `juan@example.com`
- password: `MiPassword123!`

**Respuesta:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

### 3. Verificar Edad

**Endpoint:** `POST /age-verification/verify-age`

**Headers:**
```
Authorization: Bearer {tu_token}
```

### 4. Explorar Productos

**Endpoint:** `GET /products/?category=Cerveza&min_price=500&max_price=1500`

### 5. Agregar al Carrito

**Endpoint:** `POST /cart/add`

```json
{
  "product_id": "507f1f77bcf86cd799439011",
  "quantity": 2
}
```

### 6. Crear Pedido

**Endpoint:** `POST /orders/`

```json
{
  "items": [
    {
      "product_id": "507f1f77bcf86cd799439011",
      "quantity": 2
    }
  ],
  "shipping_address": {
    "street": "Av. San Martín 1234",
    "city": "San Miguel de Tucumán",
    "state": "Tucumán",
    "zip_code": "4000",
    "country": "Argentina"
  }
}
```

---

## 🔒 Seguridad

- **JWT Tokens:** Expiración configurable (30 minutos por defecto)
- **Rate Limiting:** 5 intentos de login por minuto por IP
- **Hashing:** Bcrypt para contraseñas
- **Validación:** Pydantic para validación de entrada
- **CORS:** Configurado para producción
- **Variables de Entorno:** Credenciales nunca en código

---

## 🧪 Ejemplos de Uso con cURL

### Registrar Usuario
```bash
curl -X POST "https://web-production-62840.up.railway.app/auth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "testuser",
    "email": "test@example.com",
    "password": "Test123!",
    "birth_date": "1995-01-01T00:00:00.000Z"
  }'
```

### Obtener Token
```bash
curl -X POST "https://web-production-62840.up.railway.app/auth/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=test@example.com&password=Test123!"
```

### Listar Productos
```bash
curl -X GET "https://web-production-62840.up.railway.app/products/"
```

### Crear Producto (Admin)
```bash
curl -X POST "https://web-production-62840.up.railway.app/products/" \
  -H "Authorization: Bearer {tu_token}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Cerveza Corona 355ml",
    "description": "Cerveza mexicana importada",
    "price": 1200.00,
    "category": "Cerveza",
    "stock": 50,
    "abv": 4.5,
    "volume_ml": 355,
    "origin": "México"
  }'
```

---

## 📊 Categorías de Productos

- **Cervezas:** Quilmes, Corona, Heineken, artesanales
- **Vinos:** Tintos, Blancos, Rosados
- **Licores:** Whisky, Vodka, Gin, Ron, Tequila
- **Gaseosas:** Coca-Cola, Sprite, Fanta
- **Otros:** Jugos, aguas saborizadas, energizantes

---

## 👥 Roles de Usuario

### Cliente (Customer)
- Registrarse e iniciar sesión
- Verificar mayoría de edad
- Buscar y ver productos
- Agregar productos al carrito
- Crear pedidos
- Ver historial de pedidos

### Administrador (Admin)
- Todo lo que puede hacer un cliente
- Crear, editar y eliminar productos
- Gestionar inventario
- Ver alertas de stock
- Actualizar estados de pedidos
- Acceso a panel administrativo

---

## 🚀 Instalación Local

### Requisitos Previos
- Python 3.13+
- MongoDB
- Redis
- Git

### Pasos

1. **Clonar el repositorio**
```bash
git clone https://github.com/tu-usuario/escabi-api.git
cd escabi-api
```

2. **Crear entorno virtual**
```bash
python -m venv venv
source venv/bin/activate  # En Windows: venv\Scripts\activate
```

3. **Instalar dependencias**
```bash
pip install -r requirements.txt
```

4. **Configurar variables de entorno**

Crear archivo `.env`:
```env
SECRET_KEY=tu-secret-key-super-segura
DATABASE_URL=mongodb://localhost:27017
DATABASE_NAME=bebidas_db
REDIS_URL=redis://localhost:6379
ENV=development
MERCADOPAGO_ACCESS_TOKEN=tu-token
WEBHOOK_BASE_URL=http://localhost:8000
```

5. **Iniciar con Docker Compose (recomendado)**
```bash
docker compose up
```

O manualmente:
```bash
python main.py
```

6. **Acceder a la documentación**

Abrir navegador en: http://localhost:8000/docs

---

## 🐳 Deploy con Docker

```bash
# Construir imagen
docker build -t escabi-api .

# Ejecutar contenedor
docker run -p 8000:8000 --env-file .env escabi-api
```

---

## 📈 Roadmap

- [ ] Sistema de reseñas y calificaciones
- [ ] Recomendaciones personalizadas
- [ ] Sistema de cupones y descuentos
- [ ] Notificaciones por email
- [ ] Programa de fidelización
- [ ] API de analytics
- [ ] Integración con más pasarelas de pago
- [ ] App móvil

---

## 🤝 Contribuciones

Las contribuciones son bienvenidas. Por favor:

1. Fork el proyecto
2. Crea una rama para tu feature (`git checkout -b feature/AmazingFeature`)
3. Commit tus cambios (`git commit -m 'Add some AmazingFeature'`)
4. Push a la rama (`git push origin feature/AmazingFeature`)
5. Abre un Pull Request

---

## 📝 Licencia

Este proyecto está bajo la Licencia MIT. Ver el archivo `LICENSE` para más detalles.

---

## 👨‍💻 Autor

**Luciano Lagoria**
- GitHub: [@Dybalux](https://github.com/Dybalux)
- LinkedIn: [Tu Perfil](https://www.linkedin.com/in/luciano-emanuel-lagoria-villagr%C3%A1n-5397a421a/)
- Email: lagorialuciano@gmail.com

---

## 🙏 Agradecimientos

- FastAPI por su excelente framework
---

## 📞 Soporte

¿Encontraste un bug o tenés una sugerencia?

- 🐛 Reportar bug: [Issues](https://github.com/tu-usuario/escabi-api/issues)
- 💡 Sugerir feature: [Issues](https://github.com/tu-usuario/escabi-api/issues)
- 📧 Contacto: lagorialuciano@gmail.com

---

<div align="center">

**⭐ Si te gustó el proyecto, dale una estrella en GitHub ⭐**

Hecho con ❤️ y ☕ en Argentina 🇦🇷

</div>

