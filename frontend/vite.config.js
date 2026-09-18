import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

import { defineConfig } from 'vite';

/**
 * Fill in the service worker's precache list after the bundle is written.
 *
 * Vite content-hashes the JS and CSS filenames, so sw.js cannot name them
 * ahead of time. Without this the precache silently misses exactly the two
 * files the app cannot start without, and offline gets an unstyled skeleton.
 *
 * The build id is derived from the emitted filenames, so it changes when the
 * output changes and stays put when it does not -- the cache name carries it,
 * which is what makes a deploy evict the previous build.
 */
function pwaPrecache() {
  return {
    name: 'pwa-precache',
    apply: 'build',
    writeBundle(options, bundle) {
      const dist = options.dir || 'dist';
      const emitted = Object.keys(bundle)
        .filter(name => /\.(js|css)$/.test(name))
        .map(name => `/${name}`);
      // Everything the app needs to start with no network at all.
      const precache = ['/', '/index.html', '/manifest.webmanifest',
                        '/icon-192.png', '/icon-512.png', '/icon-maskable-512.png',
                        ...emitted];
      const build = createHash('sha256').update(emitted.sort().join('|')).digest('hex').slice(0, 12);

      const swPath = join(dist, 'sw.js');
      let sw = readFileSync(swPath, 'utf8');
      sw = sw.replace('__BUILD_ID__', build);
      sw = sw.replace(
        /\[\/\*__PRECACHE__\*\/[^\]]*\]/,
        JSON.stringify(precache),
      );
      if (sw.includes('__BUILD_ID__') || sw.includes('__PRECACHE__')) {
        throw new Error('pwa-precache: sw.js placeholders were not replaced');
      }
      writeFileSync(swPath, sw);
      console.log(`  pwa-precache  ${precache.length} files, build ${build}`);
    },
  };
}

export default defineConfig({
  // These are public backend origins, not credentials. Vite only exposes
  // variables with approved prefixes to browser code.
  envPrefix: ['VITE_', 'PRIMARY_API_URL', 'SECONDARY_API_URL'],
  plugins: [pwaPrecache()],
});
