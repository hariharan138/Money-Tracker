const PRIMARY_API_URL = import.meta.env.PRIMARY_API_URL || '';
const SECONDARY_API_URL = import.meta.env.SECONDARY_API_URL || '';
// Fail over quickly so a cold primary does not stall the UI.
const PRIMARY_TIMEOUT_MS = 3_000;

function apiUrl(baseUrl, path) {
  return new URL(path, `${baseUrl.replace(/\/$/, '')}/`).toString();
}

function devLog(message) {
  if (import.meta.env.DEV) console.info(message);
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

async function fetchPrimaryWithTimeout(url, init) {
  const controller = new AbortController();
  let timedOut = false;
  const timeout = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, PRIMARY_TIMEOUT_MS);

  const callerSignal = init.signal;
  const abortFromCaller = () => controller.abort(callerSignal?.reason);
  if (callerSignal) {
    if (callerSignal.aborted) abortFromCaller();
    else callerSignal.addEventListener('abort', abortFromCaller, { once: true });
  }

  try {
    return {
      response: await fetch(url, buildFetchInit(init, controller.signal)),
    };
  } catch (error) {
    if (callerSignal?.aborted && !timedOut) throw error;
    return { error };
  } finally {
    clearTimeout(timeout);
    callerSignal?.removeEventListener('abort', abortFromCaller);
  }
}

/**
 * Make an API request with per-request primary/secondary failover.
 *
 * Only network failures, primary timeouts, and primary 5xx responses use the
 * secondary. Authentication and normal client errors are returned unchanged.
 */
export async function apiFetch(path, init = {}) {
  if (!PRIMARY_API_URL || !SECONDARY_API_URL) {
    throw new Error('PRIMARY_API_URL and SECONDARY_API_URL must both be configured');
  }

  const primaryUrl = apiUrl(PRIMARY_API_URL, path);
  const secondaryUrl = apiUrl(SECONDARY_API_URL, path);
  const primary = await fetchPrimaryWithTimeout(primaryUrl, init);

  if (primary.response && primary.response.status < 500) return primary.response;

  devLog('Primary API failed, switching to secondary');
  // Fresh options object so a string/Blob body can be sent again safely.
  const secondaryResponse = await fetch(secondaryUrl, buildFetchInit(init));
  if (secondaryResponse.ok) devLog('Secondary API request successful');
  return secondaryResponse;
}

export function hasApiConfiguration() {
  return Boolean(PRIMARY_API_URL && SECONDARY_API_URL);
}
