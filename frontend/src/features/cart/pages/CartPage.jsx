// frontend/src/features/cart/pages/CartPage.jsx
import { Link } from 'react-router-dom';
import { useCart } from '../context/CartContext';
import { CartItemRow } from '../components/CartItemRow';

// Función simple para formatear precio
const formatPrice = (price) => {
  return new Intl.NumberFormat('es-AR', {
    style: 'currency',
    currency: 'ARS',
  }).format(price);
};

export const CartPage = () => {
  const { cart, loading, error, updateQuantity, removeFromCart, clearCart } = useCart();

  // --- ¡CÁLCULO REAL! ---
  const subtotal = cart?.items.reduce((sum, item) => {
    return sum + (item.price * item.quantity);
  }, 0) || 0;

  if (loading) {
    return <div className="text-center p-12">Cargando carrito...</div>;
  }

  if (error) {
    return <div className="text-center p-12 text-red-600">Error: {error}</div>;
  }

  if (!cart || cart.items.length === 0) {
    return (
      <div className="text-center p-12">
        <h1 className="text-3xl font-bold mb-4">Tu carrito está vacío</h1>
        <Link to="/" className="text-blue-500 hover:underline">
          Explora nuestros productos
        </Link>
      </div>
    );
  }

  return (
    <div className="container mx-auto p-4">
      <h1 className="text-3xl font-bold mb-6 text-gray-800">Tu Carrito</h1>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">

        {/* Columna de Items del Carrito */}
        <div className="lg:col-span-2 bg-white p-6 rounded-lg shadow-md">
          <table className="w-full">
            <thead>
              <tr className="border-b">
                <th className="text-left p-4 font-semibold text-gray-600">Producto</th>
                <th className="text-center p-4 font-semibold text-gray-600">Cantidad</th>
                <th className="text-right p-4 font-semibold text-gray-600">Precio</th>
                <th className="text-right p-4 font-semibold text-gray-600">Total</th>
              </tr>
            </thead>
            <tbody>
              {cart.items.map((item) => (
                <CartItemRow 
                  key={item.product_id}
                  item={item}
                  onUpdateQuantity={updateQuantity}
                  onRemove={removeFromCart}
                />
              ))}
            </tbody>
          </table>
          <button
            onClick={clearCart}
            className="mt-6 text-sm text-red-500 hover:underline"
          >
            Vaciar Carrito
          </button>
        </div>

        {/* Columna de Resumen */}
        <div className="lg:col-span-1">
          <div className="bg-white p-6 rounded-lg shadow-md sticky top-24">
            <h2 className="text-2xl font-bold mb-4">Resumen del Pedido</h2>
            <div className="flex justify-between mb-2">
             <span className="text-gray-600">Subtotal</span>
              <span className="font-semibold">{formatPrice(subtotal)}</span>
            </div>
            <div className="flex justify-between mb-4">
              <span className="text-gray-600">Envío</span>
              <span className="font-semibold">Gratis</span>
            </div>
            <div className="border-t pt-4 flex justify-between items-center">
              <span className="text-xl font-bold text-gray-900">Total</span>
              <span className="text-2xl font-bold text-blue-600">{formatPrice(subtotal)}</span>
            </div>
            <Link 
              to="/checkout"
              className="block w-full text-center mt-6 bg-green-600 text-white font-bold py-3 px-6 rounded-lg hover:bg-green-700 transition"
            >
              Proceder al Pago
            </Link>
          </div>
        </div>

      </div>
    </div>
  );
};