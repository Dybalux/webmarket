// frontend/src/features/cart/components/CartItemRow.jsx
import { useState } from 'react';

// Función simple para formatear precio
const formatPrice = (price) => {
  return new Intl.NumberFormat('es-AR', {
    style: 'currency',
    currency: 'ARS',
  }).format(price);
};

// Recibimos el 'item' y las funciones del contexto
export const CartItemRow = ({ item, onUpdateQuantity, onRemove }) => {
  // Usamos un estado local para la cantidad para no llamar a la API en cada tecleo
  const [quantity, setQuantity] = useState(item.quantity);

  const handleUpdate = () => {
    onUpdateQuantity(item.product_id, quantity);
  };

  const handleRemove = () => {
    onRemove(item.product_id);
  };

// Ahora 'item' contiene name, price, e image_url gracias al backend
  const productName = item.name || `Producto (ID: ${item.product_id})`;
  const productPrice = item.price || 0; // Usamos 0 si el precio no viene
  const productImage = item.image_url || 'https://via.placeholder.com/100x100.png?text=IMG';

  return (
    <tr className="border-b">
      <td className="p-4">
        <div className="flex items-center space-x-4">
          <img src={productImage} alt={productName} className="w-16 h-16 rounded object-cover" />
          <div>
            <p className="font-bold text-gray-800">{productName}</p>
            <button onClick={handleRemove} className="text-red-500 text-sm hover:underline">
              Eliminar
            </button>
          </div>
        </div>
      </td>
      <td className="p-4 text-center">
        <input 
          type="number"
          value={quantity}
          onChange={(e) => setQuantity(Number(e.target.value))}
          onBlur={handleUpdate} // Llama a la API cuando el usuario quita el foco
          min={1}
          className="w-20 text-center px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </td>
      <td className="p-4 text-right font-semibold">{formatPrice(productPrice)}</td>
      <td className="p-4 text-right font-bold text-lg">{formatPrice(productPrice * quantity)}</td>
    </tr>
  );
};