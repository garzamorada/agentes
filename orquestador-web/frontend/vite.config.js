import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// En desarrollo (npm run dev) la API la sirve el contenedor en :8095
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://localhost:8095' } },
});
