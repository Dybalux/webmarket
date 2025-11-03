import { Link } from 'react-router-dom';

// Este componente recibe el objeto 'product' como prop
export const ProductCard = ({ product }) => {

  // Formateamos el precio para que se vea bien
  const formatPrice = (price) => {
    return new Intl.NumberFormat('es-AR', {
      style: 'currency',
      currency: 'ARS',
    }).format(price);
  };

  return (
    // Hacemos que toda la tarjeta sea un link al detalle del producto
    <Link 
      to={`/products/${product.id}`} 
      className="bg-white rounded-lg shadow-md overflow-hidden transform transition-transform duration-300 hover:scale-105"
    >
      {/* Imagen del Producto */}
      <img 
        src={product.image_url || 'https://via.placeholder.com/300x300.png?text=Sin+Imagen'} 
        alt={product.name}
        className="w-full h-48 object-cover"
      />

      <div className="p-4">
        {/* Categoría (con Tailwind) */}
        <span className="text-xs font-semibold text-blue-600 uppercase">
          {product.category}
        </span>

        {/* Nombre del Producto */}
        <h3 className="text-lg font-bold text-gray-800 mt-1 truncate" title={product.name}>
          {product.name}
        </h3>

        {/* Precio */}
        <p className="text-2xl font-extrabold text-gray-900 my-2">
          {formatPrice(product.price)}
        </p>

        {/* Botón (simulado por ahora) */}
        <button 
          onClick={(e) => e.preventDefault()} // Previene que el Link se active al hacer clic en el botón
          className="w-full bg-blue-600 text-white font-bold py-2 px-4 rounded-lg hover:bg-blue-700 transition duration-300"
        >
          Agregar al carrito
        </button>
      </div>
    </Link>
  );
};