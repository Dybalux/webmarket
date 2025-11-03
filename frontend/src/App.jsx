// frontend/src/App.jsx
import { Routes, Route } from 'react-router-dom';
import { Navbar } from './components/layout/Navbar';
import { ProtectedRoute } from './components/routing/ProtectedRoute';

// Importamos las páginas de sus nuevas ubicaciones
import { HomePage } from './pages/HomePage';
import { LoginPage } from './features/auth/pages/LoginPage';
import { RegisterPage } from './features/auth/pages/RegisterPage';
import { ProductDetailPage } from './features/products/pages/ProductDetailPage';
import { ProfilePage } from './features/profile/pages/ProfilePage'; 
import { CartPage } from './features/cart/pages/CartPage';
import { CheckoutPage } from './features/checkout/pages/CheckoutPage';

function App() {
  return (
    <div className="min-h-screen bg-gray-100">
      <Navbar />

      <main className="container mx-auto p-4">
        <Routes>
          {/* --- Rutas Públicas --- */}
          <Route path="/" element={<HomePage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/products/:id" element={<ProductDetailPage />} />

          {/* --- Rutas Protegidas --- */}
          <Route element={<ProtectedRoute />}>
            <Route path="/profile" element={<ProfilePage />} />
            <Route path="/cart" element={<CartPage />} />
            <Route path="/checkout" element={<CheckoutPage />} />
          </Route>

        </Routes>
      </main>
    </div>
  );
}

export default App;