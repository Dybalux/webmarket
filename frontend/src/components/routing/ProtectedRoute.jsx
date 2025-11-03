// frontend/src/components/routing/ProtectedRoute.jsx
import { useAuth } from '../../features/auth/context/AuthContext';
import { Navigate, Outlet } from 'react-router-dom';

// Este componente revisa si el usuario está logueado
// Si no, lo redirige al login
export const ProtectedRoute = () => {
  const { isAuthenticated, loading } = useAuth();

  // No mostrar nada mientras se verifica el token
  if (loading) {
    return null; 
  }

  if (!isAuthenticated) {
    // Redirige al login si no está autenticado
    return <Navigate to="/login" replace />;
  }

  // Si está autenticado, muestra la página hija (ej: ProfilePage)
  return <Outlet />;
};