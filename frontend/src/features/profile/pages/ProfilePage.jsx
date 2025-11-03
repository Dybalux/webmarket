import { useAuth } from '../../auth/context/AuthContext';
import { apiFetch } from '../../../lib/api';
import { useState } from 'react';

export const ProfilePage = () => {
  // Obtenemos el usuario y una forma de actualizarlo (que agregaremos)
  const { user, setUser, logout } = useAuth(); 
  const [error, setError] = useState(null);
  const [message, setMessage] = useState(null);

  const handleVerifyAge = async () => {
    setError(null);
    setMessage(null);
    try {
      // 1. Llamamos al endpoint de verificación
      //
      const updatedUser = await apiFetch('/age-verification/verify-age', {
        method: 'POST',
      });

      // 2. Actualizamos el usuario en nuestro estado global
      setUser(updatedUser);
      setMessage('¡Verificación exitosa! Ahora puedes comprar.');

    } catch (err) {
      // El backend devuelve 403 si es menor de edad
      setError(err.message || 'Error al verificar la edad.');
    }
  };

  if (!user) {
    return <div className="p-8 text-center">No estás logueado.</div>;
  }

  return (
    <div className="max-w-2xl mx-auto bg-white p-8 rounded-lg shadow-md">
      <h1 className="text-3xl font-bold mb-6 text-gray-800">Mi Perfil</h1>

      <div className="space-y-4">
        <p><strong className="text-gray-700">Username:</strong> {user.username}</p>
        <p><strong className="text-gray-700">Email:</strong> {user.email}</p>
        <p><strong className="text-gray-700">Rol:</strong> {user.role}</p>

        {/* --- Lógica de Verificación de Edad --- */}
        <div className={`p-4 rounded-lg ${user.age_verified ? 'bg-green-100 text-green-800' : 'bg-yellow-100 text-yellow-800'}`}>
          <h3 className="font-bold text-lg mb-2">Verificación de Edad</h3>
          {user.age_verified ? (
            <p>✅ ¡Tu mayoría de edad ha sido verificada!</p>
          ) : (
            <div>
              <p className="mb-4">❌ Aún no has verificado tu mayoría de edad. Necesitas hacerlo para poder comprar.</p>
              <button 
                onClick={handleVerifyAge}
                className="bg-blue-600 text-white font-bold py-2 px-4 rounded-lg hover:bg-blue-700 transition"
              >
                Verificar mi edad ahora
              </button>
            </div>
          )}
        </div>

        {/* Mostrar mensajes de error o éxito */}
        {error && <div className="text-red-600 p-3 bg-red-100 rounded">{error}</div>}
        {message && <div className="text-green-600 p-3 bg-green-100 rounded">{message}</div>}

      </div>

      <button
        onClick={logout}
        className="w-full bg-red-600 text-white font-bold py-2 px-4 rounded-lg hover:bg-red-700 transition mt-8"
      >
        Cerrar Sesión
      </button>
    </div>
  );
};