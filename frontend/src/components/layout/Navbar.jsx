// frontend/src/components/layout/Navbar.jsx
import { Link } from 'react-router-dom';
import { useAuth } from '../../features/auth/context/AuthContext';
export const Navbar = () => {
  const { isAuthenticated, user } = useAuth(); // Leemos el estado global

  return (
    <nav className="bg-gray-800 text-white p-4 shadow-md">
      <div className="container mx-auto flex justify-between items-center">

        {/* Logo o Título del Sitio */}
        <Link to="/" className="text-2xl font-bold text-blue-400">
          WebMarket
        </Link>

        {/* Links de Navegación */}
        <div className="space-x-4">
          <Link to="/" className="hover:text-blue-300">Home</Link>
          <Link to="/products" className="hover:text-blue-300">Productos</Link>

          {/* Esto cambiará según el login */}
          {isAuthenticated ? (
            <>
              <Link to="/profile" className="hover:text-blue-300">
                Hola, {user ? user.username : 'Usuario'}
              </Link>
              <button className="hover:text-red-400">(Logout)</button>
            </>
          ) : (
            <>
              <Link to="/login" className="hover:text-blue-300">Login</Link>
              <Link to="/register" className="hover:text-blue-300">Registrarse</Link>
            </>
          )}
        </div>
      </div>
    </nav>
  );
};