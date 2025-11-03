// frontend/src/App.jsx
import { Routes, Route } from 'react-router-dom';
import { Navbar } from './components/layout/Navbar';

// Importamos las páginas de sus nuevas ubicaciones
import { HomePage } from './pages/HomePage';
import { LoginPage } from './features/auth/pages/LoginPage';
import { RegisterPage } from './features/auth/pages/RegisterPage';

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
          
          {/* Aquí irán las rutas de productos, carrito, etc. */}
        </Routes>
      </main>
    </div>
  );
}

export default App;