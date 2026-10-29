// Calls to /api/v1 with the session. Writes send Django's CSRF token, which
// every page carries in <meta name="csrf-token"> (base.html); there is no
// CSRF cookie (CSRF_USE_SESSIONS).

function csrfToken() {
  return document.querySelector('meta[name="csrf-token"]')?.content || '';
}

/** Returns {status, ok, data, etag}; never throws for HTTP errors. */
export async function api(method, path, body, headers = {}) {
  const opts = { method, credentials: 'same-origin', headers: { Accept: 'application/json', ...headers } };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  if (method !== 'GET') opts.headers['X-CSRFToken'] = csrfToken();
  const response = await fetch('/api/v1' + path, opts);
  const json = (response.headers.get('Content-Type') || '').includes('application/json');
  return {
    status: response.status,
    ok: response.ok,
    data: json ? await response.json() : null,
    etag: response.headers.get('ETag'),
  };
}

export const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

// Waits before retrying a call that failed on the way: a transient proxy error
// or dropped connection shouldn't lose a job or a published changeset.
const RETRY_WAITS = [1000, 2000, 4000];

/**
 * Run `call()` (an api() call), retrying after 1, 2 and 4 s if the network
 * fails or the server answers 429 or 5xx; other errors won't get better.
 * Returns the last result, with status 0 for a network error.
 */
export async function retrying(call, waits = RETRY_WAITS) {
  for (let i = 0; ; i++) {
    let r;
    try {
      r = await call();
    } catch (e) {
      r = { status: 0, ok: false, data: { detail: `Network error: ${e.message}` }, etag: null };
    }
    const transient = r.status === 0 || r.status === 429 || r.status >= 500;
    if (r.ok || !transient || i === waits.length) return r;
    await sleep(waits[i]);
  }
}

/** The error text of a failed call. */
export function problem(result) {
  return result.data?.detail || `Request failed (HTTP ${result.status}).`;
}

export function pageData() {
  const el = document.getElementById('page-data');
  return el ? JSON.parse(el.textContent) : {};
}
