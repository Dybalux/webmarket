// frontend/src/features/auth/context/AuthContext.jsx
import { createContext, useContext, useState, useEffect } from 'react';
import { apiFetch, loginApi } from '../../../lib/api'; // Importamos el cliente API
import { useNavigate } from 'react-router-dom';

const AuthContext = createContext();

export const AuthProvider = ({ children }) => {
  const navigate = useNavigate();
  const [token, setToken] = useState(() => localStorage.getItem('token')); // Lee el token al cargar
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true); // Para saber si estamos verificando el token

  const isAuthenticated = !!token;

  // Al cargar, si hay un token, verifica quién es el usuario
  useEffect(() => {
    const fetchUser = async () => {
      if (token) {
        try {
          // Llama a /auth/me para obtener los datos del usuario
          const userData = await apiFetch('/auth/me');
          setUser(userData);
        } catch (error) {
          console.error("Token inválido, limpiando.");
          logout(); // Limpia si el token es malo
        }
      }
      setLoading(false);
    };
    fetchUser();
  }, [token]); // Se ejecuta cada vez que el token cambia

  // Función de Login
  const login = async (username, password) => {
    try {
      // 1. Llama al endpoint de login (que es especial, usa formulario)
      const data = await loginApi(username, password); // { access_token: "..." }

      // 2. Guarda el token en el estado y localStorage
      setToken(data.access_token);
      localStorage.setItem('token', data.access_token);

      // 3. Obtiene los datos del usuario (ya que el token está seteado, el useEffect se disparará)
      // O podemos llamarlo manualmente para asegurar:
      const userData = await apiFetch('/auth/me');
      setUser(userData);

    } catch (error) {
      console.error("Error al iniciar sesión:", error);
      throw error; // Lanza el error para que el formulario de login lo muestre
    }
  };

  // --- ¡NUEVA FUNCIÓN DE REGISTRO! ---
  const register = async (username, email, password, birth_date) => {
    try {
      // 1. Llama al endpoint de registro
      const newUser = await apiFetch('/auth/register', {
        method: 'POST',
        body: { username, email, password, birth_date }
      }); //
      
      // 2. Si el registro es exitoso, loguea al usuario automáticamente
      await login(email, password); // Usa el email o username para loguear
      
      // 3. Redirige al Home (o a donde quieras)
      navigate('/'); 

    } catch (error) {
      console.error("Error al registrar:", error);
      throw error; // Lanza el error para que el formulario lo muestre
    }
  };

  // Función de Logout
  const logout = () => {
    setToken(null);
    setUser(null);
    localStorage.removeItem('token');
  };

  const value = {
    token,
    user,
    isAuthenticated,
    loading,
    login,
    logout,
    register,
    setUser,
  };

  // No mostramos nada hasta saber si estamos logueados o no
  if (loading) {
    return <div className="p-8 text-center">Cargando...</div>; 
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth debe ser usado dentro de un AuthProvider");
  }
  return context;
};