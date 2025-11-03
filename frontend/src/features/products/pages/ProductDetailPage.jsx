// frontend/src/features/products/pages/ProductDetailPage.jsx
import { useState, useEffect } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { apiFetch } from '../../../lib/api'; // Nuestro cliente API
import { useCart } from '../../../features/cart/context/CartContext';
import { useAuth } from '../../../features/auth/context/AuthContext';

// Función simple para formatear precio
const formatPrice = (price) => {
  return new Intl.NumberFormat('es-AR', {
    style: 'currency',
    currency: 'ARS',
  }).format(price);
};

export const ProductDetailPage = () => {
  const [product, setProduct] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [quantity, setQuantity] = useState(1);
  const [actionMessage, setActionMessage] = useState(null);

  // 1. Obtenemos el 'id' de la URL (ej: /products/123ab)
  const { id } = useParams(); 
  const navigate = useNavigate();

  // --- Hooks de Contexto ---
  const { isAuthenticated, user } = useAuth(); // Info del usuario
  const { addToCart } = useCart(); // Función del carrito

  // 2. Usamos useEffect para buscar el producto cuando el 'id' cambia
  useEffect(() => {
    const fetchProduct = async () => {
      try {
        setLoading(true);
        setError(null);

        // Llamamos al endpoint de la API para un producto
        const data = await apiFetch(`/products/${id}`);
        setProduct(data);

      } catch (err) {
        setError(err.message || 'No se pudo cargar el producto.');
      } finally {
        setLoading(false);
      }
    };

    if (id) {
      fetchProduct();
    }
  }, [id]); // Este efecto se re-ejecuta si el 'id' de la URL cambia

  // --- ¡NUEVA FUNCIÓN! ---
  const handleAddToCart = async () => {
    setActionMessage(null);

    // 1. Revisar si está logueado
    if (!isAuthenticated) {
      navigate('/login'); // Redirige al login
      return;
    }

    // 2. Revisar si está verificado
    if (!user.age_verified) {
      setActionMessage({ type: 'error', text: 'Debes verificar tu edad en tu perfil para comprar.' });
      return;
    }

    // 3. Agregar al carrito
    try {
      await addToCart(product.id, quantity);
      setActionMessage({ type: 'success', text: '¡Producto añadido al carrito!' });
    } catch (err) {
      setActionMessage({ type: 'error', text: err.message || 'Error al añadir al carrito.' });
    }
  };

  // --- Renderizado Condicional ---
  if (loading) {
    return <div className="text-center p-12">Cargando producto...</div>;
  }

  if (error) {
    return <div className="text-center p-12 text-red-600">Error: {error}</div>;
  }

  if (!product) {
     return <div className="text-center p-12">Producto no encontrado.</div>;
  }

  // --- Renderizado del Producto ---
  // Usamos los campos de tu modelo 'Product'
  return (
    <div className="bg-white p-8 rounded-lg shadow-lg max-w-4xl mx-auto">
      <Link to="/" className="text-blue-500 hover:underline mb-6 inline-block">
        &larr; Volver al catálogo
      </Link>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        {/* ... (Columna de Imagen se queda igual) ... */}
        <div>
          <img
            src={product.image_url || 'https://via.placeholder.com/400x400.png?text=Sin+Imagen'}
            alt={product.name}
            className="w-full h-auto rounded-lg shadow-sm object-cover"
          />
        </div>

        {/* Columna de Detalles (Actualizada) */}
        <div className="flex flex-col justify-center">
          {/* ... (Título, precio, descripción, detalles... todo igual) ... */}
          <span className="text-sm font-semibold text-blue-600 uppercase">{product.category}</span>
          <h1 className="text-4xl font-bold text-gray-900 mt-2">{product.name}</h1>
          <p className="text-3xl font-extrabold text-gray-800 my-4">{formatPrice(product.price)}</p>
          <p className="text-gray-600 text-lg mb-4">{product.description || "Sin descripción."}</p>
          <div className="text-gray-600 space-y-1 mb-6 border-t pt-4">
            <p><strong>Stock:</strong> {product.stock} unidades</p>
            {product.abv && <p><strong>Graduación:</strong> {product.abv}%</p>}
            {product.volume_ml && <p><strong>Volumen:</strong> {product.volume_ml}ml</p>}
            {product.origin && <p><strong>Origen:</strong> {product.origin}</p>}
          </div>

          {/* Controles para añadir al carrito (Actualizados) */}
          <div className="flex items-center gap-4">
            <input 
              type="number"
              value={quantity}
              onChange={(e) => setQuantity(Number(e.target.value))}
              min={1}
              max={product.stock}
              className="w-20 text-center px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <button 
              onClick={handleAddToCart} // <-- Conectamos la función
              className="flex-1 bg-blue-600 text-white font-bold py-3 px-6 rounded-lg hover:bg-blue-700 transition duration-300"
            >
              Agregar al Carrito
            </button>
          </div>

          {/* Mensajes de feedback */}
          {actionMessage && (
            <div className={`mt-4 text-center font-semibold p-3 rounded-lg ${
              actionMessage.type === 'success' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
            }`}>
              {actionMessage.text}
            </div>
          )}

        </div>
      </div>
    </div>
  );
};