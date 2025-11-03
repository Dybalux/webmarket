// frontend/src/features/checkout/components/AddressForm.jsx
import { useState } from 'react';

export const AddressForm = ({ onSubmit, isSubmitting }) => {
  // El modelo 'Address' requiere: street, city, state, zip_code, country
  const [street, setStreet] = useState('');
  const [city, setCity] = useState('');
  const [state, setState] = useState(''); // Provincia
  const [zip_code, setZipCode] = useState(''); // Código Postal
  const [country, setCountry] = useState('Argentina'); // País (fijamos uno por defecto)

  const handleSubmit = (e) => {
    e.preventDefault();
    onSubmit({ street, city, state, zip_code, country });
  };

  return (
    <form onSubmit={handleSubmit} className="bg-white p-8 rounded-lg shadow-md">
      <h2 className="text-2xl font-bold mb-6 text-gray-800">Dirección de Envío</h2>

      <div className="mb-4">
        <label htmlFor="street" className="block text-gray-700 font-bold mb-2">Calle y Número</label>
        <input
          type="text" id="street" value={street}
          onChange={(e) => setStreet(e.target.value)}
          className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          required
        />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
        <div>
          <label htmlFor="city" className="block text-gray-700 font-bold mb-2">Ciudad</label>
          <input
            type="text" id="city" value={city}
            onChange={(e) => setCity(e.target.value)}
            className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            required
          />
        </div>
        <div>
          <label htmlFor="zip_code" className="block text-gray-700 font-bold mb-2">Código Postal</label>
          <input
            type="text" id="zip_code" value={zip_code}
            onChange={(e) => setZipCode(e.target.value)}
            className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            required
          />
        </div>
      </div>

      <div className="mb-6">
        <label htmlFor="state" className="block text-gray-700 font-bold mb-2">Provincia</label>
        <input
          type="text" id="state" value={state}
          onChange={(e) => setState(e.target.value)}
          className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          required
        />
      </div>
      {/* El país está fijado, pero podrías hacerlo un 'select' */}

      <button 
        type="submit"
        disabled={isSubmitting}
        className="w-full bg-green-600 text-white font-bold py-3 px-4 rounded-lg hover:bg-green-700 transition duration-300 disabled:bg-gray-400"
      >
        {isSubmitting ? 'Procesando...' : 'Confirmar y Pagar'}
      </button>
    </form>
  );
};