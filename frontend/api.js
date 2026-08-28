const PRIMARY_API_URL = import.meta.env.PRIMARY_API_URL || '';
const SECONDARY_API_URL = import.meta.env.SECONDARY_API_URL || '';
const PRIMARY_TIMEOUT_MS = 8_000;

function apiUrl(baseUrl, path) {
  return new URL(path, `${baseUrl.replace(/\/$/, '')}/`).toString();
}

function devLog(message) {
  if (import.meta.env.DEV) console.info(message);
}

async function fetchPrimaryWithTimeout(request) {
  const controller = new AbortController();
  let timedOut = false;
  const timeout = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, PRIMARY_TIMEOUT_MS);
  const abortFromCaller = () => controller.abort(request.signal.reason);

  if (request.signal.aborted) abortFromCaller();
  else request.signal.addEventListener('abort', abortFromCaller, { once: true });

  try {
    return { response: await fetch(request, { signal: controller.signal }) };
  } catch (error) {
    // An abort initiated by the caller is not a backend failure and must keep
    // the usual fetch cancellation behavior.
    if (request.signal.aborted && !timedOut) throw error;
    return { error };
  } finally {
    clearTimeout(timeout);
    request.signal.removeEventListener('abort', abortFromCaller);
  }
}

/**
 * Make an API request with per-request primary/secondary failover.
 *
 * Only network failures, primary timeouts, and primary 5xx responses use the
 * secondary. Authentication and normal client errors are returned unchanged.
 * The Request copies ensure the method, headers, body, query string,
 * credentials, and other fetch options are identical for both attempts.
 */
export async function apiFetch(path, init = {}) {
  if (!PRIMARY_API_URL || !SECONDARY_API_URL) {
    throw new Error('PRIMARY_API_URL and SECONDARY_API_URL must both be configured');
  }

  const primaryRequest = new Request(apiUrl(PRIMARY_API_URL, path), init);
  // Clone before the first request so bodies (including FormData uploads) are
  // still available if the primary must be retried against the secondary.
  const secondaryRequest = new Request(
    apiUrl(SECONDARY_API_URL, path),
    primaryRequest.clone(),
  );
  const primary = await fetchPrimaryWithTimeout(primaryRequest);

  if (primary.response && primary.response.status < 500) return primary.response;

  devLog('Primary API failed, switching to secondary');
  const secondaryResponse = await fetch(secondaryRequest);
  if (secondaryResponse.ok) devLog('Secondary API request successful');
  return secondaryResponse;
}

export function hasApiConfiguration() {
  return Boolean(PRIMARY_API_URL && SECONDARY_API_URL);
}
