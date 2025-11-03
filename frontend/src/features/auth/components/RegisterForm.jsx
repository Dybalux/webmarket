// frontend/src/features/auth/components/RegisterForm.jsx
import { useState } from 'react';
import { useAuth } from '../context/AuthContext';

export const RegisterForm = () => {
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [birth_date, setBirthDate] = useState(''); // <--- Campo de fecha
  const [error, setError] = useState(null);
  const { register } = useAuth();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);

    // Validación simple de fecha (YYYY-MM-DD)
    if (!birth_date.match(/^\d{4}-\d{2}-\d{2}$/)) {
        setError("Formato de fecha debe ser YYYY-MM-DD");
        return;
    }

    // Convertimos la fecha a un string ISO 8601 completo como pide la API
    // (Tu API espera un datetime, así que enviamos una fecha y hora)
    const isoBirthDate = `${birth_date}T00:00:00Z`;

    try {
      await register(username, email, password, isoBirthDate);
      // La redirección ocurre dentro del AuthContext
    } catch (err) {
      setError(err.message || 'Error al registrarse');
    }
  };

  return (
    <form onSubmit={handleSubmit} className="max-w-md mx-auto bg-white p-8 rounded-lg shadow-md">
      {error && (
        <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded mb-4">
          {error}
        </div>
      )}

      <div className="mb-4">
        <label htmlFor="username" className="block text-gray-700 font-bold mb-2">Username</label>
        <input
          type="text"
          id="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          required
        />
      </div>

      <div className="mb-4">
        <label htmlFor="email" className="block text-gray-700 font-bold mb-2">Email</label>
        <input
          type="email"
          id="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          required
        />
      </div>

      <div className="mb-4">
        <label htmlFor="password" className="block text-gray-700 font-bold mb-2">Contraseña</label>
        <input
          type="password"
          id="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          minLength={8}
          required
        />
      </div>

      <div className="mb-6">
        <label htmlFor="birth_date" className="block text-gray-700 font-bold mb-2">Fecha de Nacimiento</label>
        <input
          type="date" // El input de tipo 'date' nos da el formato YYYY-MM-DD
          id="birth_date"
          value={birth_date}
          onChange={(e) => setBirthDate(e.target.value)}
          className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          required
        />
      </div>

      <button 
        type="submit"
        className="w-full bg-green-600 text-white font-bold py-2 px-4 rounded-lg hover:bg-green-700 transition duration-300"
      >
        Crear Cuenta
      </button>
    </form>
  );
};