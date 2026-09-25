const API_URL = import.meta.env.PRIMARY_API_URL || '';
// Vercel serverless cold starts (function init + a fresh MongoDB Atlas
// connection) can take several seconds -- long enough that a short timeout
// here would abort a request that was merely slow, not actually stuck.
// Bounding every request (not just GETs) means a genuinely dead network
// still fails the promise instead of leaving the UI on a spinner forever.
const REQUEST_TIMEOUT_MS = 10_000;

function apiUrl(path) {
  return new URL(path, `${API_URL.replace(/\/$/, '')}/`).toString();
}

/**
 * Build plain fetch options. Never wrap in Request/clone — Safari rejects
 * ReadableStream request bodies ("ReadableStream uploading is not supported").
 */
function buildFetchInit(init = {}, signal) {
  const headers = new Headers(init.headers || {});
  const next = {
    method: init.method || 'GET',
    headers,
    cache: init.cache,
    credentials: init.credentials,
    mode: init.mode,
    redirect: init.redirect,
    referrer: init.referrer,
    referrerPolicy: init.referrerPolicy,
  };
  if (init.body != null) next.body = init.body;
  if (signal) next.signal = signal;
  return next;
}

/**
 * Make an API request with a hard timeout, so a stalled connection fails
 * the promise instead of hanging until the caller gives up.
 */
export async function apiFetch(path, init = {}) {
  if (!API_URL) {
    throw new Error('PRIMARY_API_URL must be configured');
  }

  const url = apiUrl(path);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  const callerSignal = init.signal;
  const abortFromCaller = () => controller.abort(callerSignal?.reason);
  if (callerSignal) {
    if (callerSignal.aborted) abortFromCaller();
    else callerSignal.addEventListener('abort', abortFromCaller, { once: true });
  }

  try {
    return await fetch(url, buildFetchInit(init, controller.signal));
  } finally {
    clearTimeout(timeout);
    callerSignal?.removeEventListener('abort', abortFromCaller);
  }
}

export function hasApiConfiguration() {
  return Boolean(API_URL);
}
