import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// Same-origin /api proxy so the httpOnly synora_token cookie works in dev without CORS.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: { '/api': { target: 'http://localhost:4000', changeOrigin: true, ws: true } },
  },
});
