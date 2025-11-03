import { ProductList } from '../features/products/components/ProductList';

export const HomePage = () => (
  <div>
    <div className="bg-blue-700 text-white p-12 rounded-lg mb-8 text-center">
      <h1 className="text-4xl font-bold mb-2">¡Bienvenido a WebMarket!</h1>
      <p className="text-xl">Tu tienda de bebidas online.</p>
    </div>

    {/* Aquí renderizamos la lista de productos */}
    <ProductList />
  </div>
);