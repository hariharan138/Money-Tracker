import { defineConfig } from 'vite';

export default defineConfig({
  // These are public backend origins, not credentials. Vite only exposes
  // variables with approved prefixes to browser code.
  envPrefix: ['VITE_', 'PRIMARY_API_URL', 'SECONDARY_API_URL'],
});
