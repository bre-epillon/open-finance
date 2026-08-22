import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Mirrors open-finance/frontend/vite.config.js, on its own port so both
// dashboards can run at once.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3100,
    host: '0.0.0.0',   // bind all interfaces so the container port mapping works
    watch: {
      usePolling: true // hot reload does not see host FS events from inside Docker
    }
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          charts: ['chart.js', 'react-chartjs-2'],
          vendor: ['react', 'react-dom']
        }
      }
    }
  }
});
