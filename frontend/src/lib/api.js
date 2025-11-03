// Esta es la URL de tu backend en Docker Compose
const API_URL = 'http://localhost:8000'; 

// Función wrapper para fetch
export const apiFetch = async (endpoint, options = {}) => {
  const { body, ...customConfig } = options;

  const token = localStorage.getItem('token'); // Leemos el token

  const headers = {
    'Content-Type': 'application/json',
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const config = {
    method: options.method || (body ? 'POST' : 'GET'),
    headers,
    ...customConfig,
  };

  if (body) {
    config.body = JSON.stringify(body);
  }

  try {
    const response = await fetch(`${API_URL}${endpoint}`, config);

    if (!response.ok) {
      // Si falla, intentamos leer el error de FastAPI
      const errorData = await response.json();
      throw new Error(errorData.detail || 'Error en la solicitud');
    }

    // Si el método es DELETE o la respuesta no tiene contenido (204)
    if (response.status === 204 || customConfig.method === 'DELETE') {
      return null; // No hay JSON que parsear
    }

    return await response.json();
  } catch (error) {
    console.error('Error en apiFetch:', error);
    throw error;
  }
};

// Función específica para el login (que usa un formulario, no JSON)
export const loginApi = async (username, password) => {
  const formData = new URLSearchParams();
  formData.append('username', username);
  formData.append('password', password);

  try {
    const response = await fetch(`${API_URL}/auth/token`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: formData,
    });

    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(errorData.detail || 'Credenciales incorrectas');
    }

    return await response.json(); // Devuelve { access_token: "...", token_type: "bearer" }
  } catch (error) {
    console.error('Error en loginApi:', error);
    throw error;
  }
};