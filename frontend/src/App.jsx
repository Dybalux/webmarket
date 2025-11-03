// frontend/src/App.jsx
import { Routes, Route } from 'react-router-dom';
import { Navbar } from './components/layout/Navbar';

// Importamos las páginas de sus nuevas ubicaciones
import { HomePage } from './pages/HomePage';
import { LoginPage } from './features/auth/pages/LoginPage';
import { RegisterPage } from './features/auth/pages/RegisterPage';
import { ProductDetailPage } from './features/products/pages/ProductDetailPage';

function App() {
  return (
    <div className="min-h-screen bg-gray-100">
      <Navbar />

      <main className="container mx-auto p-4">
        <Routes>
          {/* Rutas Públicas */}
          <Route path="/" element={<HomePage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />

          {/* --- ¡NUEVA RUTA! --- */}
          {/* Esta ruta captura el 'id' dinámicamente */}
          <Route path="/products/:id" element={<ProductDetailPage />} />

          {/* Aquí irán las rutas de productos, carrito, etc. */}
        </Routes>
      </main>
    </div>
  );
}

export default App;