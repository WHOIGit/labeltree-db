// Calls to /api/v1 with the session. Writes send Django's CSRF token.

function csrfToken() {
  const m = document.cookie.match(/(?:^|; )csrftoken=([^;]*)/);
  return m ? decodeURIComponent(m[1]) : '';
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

/** The error text of a failed call. */
export function problem(result) {
  return result.data?.detail || `Request failed (HTTP ${result.status}).`;
}

export function pageData() {
  const el = document.getElementById('page-data');
  return el ? JSON.parse(el.textContent) : {};
}
