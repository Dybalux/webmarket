// frontend/src/main.jsx (MODIFICADO)
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'; // <--- 1. Importar Router
import { AuthProvider } from './features/auth/context/AuthContext'; // <--- 2. Importar Auth

import './index.css'
import App from './App.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <AuthProvider> {/* <--- 3. Envolver con el "cerebro" */}
      <BrowserRouter> {/* <--- 4. Envolver con el Router */}
        <App />
      </BrowserRouter>
    </AuthProvider>
  </StrictMode>,
)