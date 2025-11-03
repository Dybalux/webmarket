import { useState, useEffect } from 'react';
import { apiFetch } from '../../../lib/api'; // Importamos nuestro cliente API
import { ProductCard } from './ProductCard'; // Importamos la tarjeta

export const ProductList = () => {
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchProducts = async () => {
      try {
        setLoading(true);
        setError(null);
        // Llamamos al endpoint público de productos
        const data = await apiFetch('/products');
        setProducts(data);
      } catch (err) {
        setError(err.message || 'No se pudieron cargar los productos.');
      } finally {
        setLoading(false);
      }
    };

    fetchProducts();
  }, []); // El array vacío [] asegura que se ejecute solo una vez

  // Manejo de estados
  if (loading) {
    return <div className="text-center p-8">Cargando productos...</div>;
  }

  if (error) {
    return <div className="text-center p-8 text-red-600">Error: {error}</div>;
  }

  return (
    // Grid de Tailwind para mostrar los productos
    <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-6">
      {products.map((product) => (
        <ProductCard key={product.id} product={product} />
      ))}
    </div>
  );
};