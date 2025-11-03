import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite' // <-- ¡Ahora sí va a encontrar este paquete!

// https://vite.dev/config/
export default defineConfig({
  base: "/",
  plugins: [
    react(),
    tailwindcss(), // <-- Y ahora sí lo podemos usar como plugin
  ],
})