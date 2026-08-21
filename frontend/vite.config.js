import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    host: '0.0.0.0',   // bind all interfaces so the container port mapping works
    watch: {
      usePolling: true // hot reload does not see host FS events from inside Docker
    }
  },
  build: {
    rollupOptions: {
      output: {
        // Chart.js is ~180KB of the bundle and changes far less often than the
        // app code. Splitting it out keeps the app chunk under Vite's 500KB
        // warning threshold and lets the browser cache the chart library across
        // deploys instead of redownloading it with every frontend change.
        manualChunks: {
          charts: ['chart.js', 'react-chartjs-2'],
          vendor: ['react', 'react-dom', 'react-router-dom']
        }
      }
    }
  }
});
