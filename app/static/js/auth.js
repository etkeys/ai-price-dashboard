/**
 * Shared authentication client module.
 *
 * Single source of truth for session token storage and retrieval.
 * All protected fetch calls go through authFetch() to centrally handle
 * 401 expiry and re-render the header as signed-out.
 *
 * Hard rules:
 * - The API key is passed to signIn() and immediately discarded.
 * - Only the exchanged session token is persisted to sessionStorage.
 * - Never console.log a token, key, or response containing either.
 */

const AUTH_STORAGE_KEY = 'apd.session';

/**
 * Read the stored session token and metadata from sessionStorage.
 * @returns {{token: string, name: string, role: string, expires_at: string} | null}
 */
function getToken() {
  const stored = sessionStorage.getItem(AUTH_STORAGE_KEY);
  if (!stored) return null;
  try {
    return JSON.parse(stored);
  } catch {
    return null;
  }
}

/**
 * Write token and metadata to sessionStorage.
 * @param {string} token - the session token (apds.*)
 * @param {{name: string, role: string, expires_at: string}} metadata - token metadata
 */
function setToken(token, metadata) {
  if (!token || !metadata) {
    clearToken();
    return;
  }
  const stored = { token, ...metadata };
  sessionStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(stored));
}

/**
 * Clear the session token and metadata from sessionStorage.
 */
function clearToken() {
  sessionStorage.removeItem(AUTH_STORAGE_KEY);
}

/**
 * Fetch wrapper that injects Authorization header and centrally handles 401.
 * Automatically clears stale tokens and re-renders the header.
 *
 * @param {string} url - endpoint URL
 * @param {object} options - fetch options (method, body, headers, etc.)
 * @returns {Promise<Response>}
 */
async function authFetch(url, options = {}) {
  const token = getToken();
  const headers = { ...options.headers };

  if (token && token.token) {
    headers['Authorization'] = `Bearer ${token.token}`;
  }

  if (options.body && typeof options.body === 'object') {
    headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(options.body);
  } else if (options.body && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }

  const response = await fetch(url, { ...options, headers });

  // Central 401 handler: token is stale, clear it and re-render header.
  if (response.status === 401) {
    clearToken();
    renderAuthHeader();
  }

  return response;
}

/**
 * Exchange an API key for a session token.
 *
 * @param {string} apiKey - the full apdk.* token
 * @returns {Promise<{ok: boolean, error?: string}>}
 */
async function signIn(apiKey) {
  if (!apiKey || !apiKey.trim()) {
    return { ok: false, error: 'API key is required' };
  }

  try {
    const response = await fetch('/auth/session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key: apiKey.trim() }),
    });

    if (response.status === 201) {
      const data = await response.json();
      setToken(data.token, {
        name: data.name,
        role: data.role,
        expires_at: data.expires_at,
      });
      renderAuthHeader();
      return { ok: true };
    } else if (response.status === 429) {
      const data = await response.json();
      const retryAfter = response.headers.get('Retry-After');
      return {
        ok: false,
        error: data.error || 'Too many attempts, try again later',
        retryAfter: retryAfter ? parseInt(retryAfter) : undefined,
      };
    } else {
      // Uniform error: do not distinguish 401 causes.
      return { ok: false, error: 'Invalid key' };
    }
  } catch (err) {
    return { ok: false, error: 'Network error' };
  }
}

/**
 * Sign out: revoke the session server-side, then clear local token.
 * Clear token even on network failure.
 *
 * @returns {Promise<{ok: boolean}>}
 */
async function signOut() {
  const token = getToken();
  if (!token) {
    renderAuthHeader();
    return { ok: true };
  }

  try {
    const response = await authFetch('/auth/session', { method: 'DELETE' });
    clearToken();
    renderAuthHeader();
    return { ok: response.ok };
  } catch {
    // Network failure: clear locally regardless.
    clearToken();
    renderAuthHeader();
    return { ok: false };
  }
}

/**
 * Get the current principal metadata (name, role) or null if not signed in.
 * @returns {{name: string, role: string} | null}
 */
function currentPrincipal() {
  const token = getToken();
  if (!token) return null;
  return { name: token.name, role: token.role };
}

/**
 * Check if the current principal is an administrator (cosmetic only).
 * Server remains the authority; this gates UI visibility.
 *
 * @returns {boolean}
 */
function isAdministrator() {
  const principal = currentPrincipal();
  return principal && principal.role === 'administrator';
}

/**
 * Render the header auth control based on signed-in state.
 * Called on page load and after sign-in/sign-out/401.
 */
function renderAuthHeader() {
  const container = document.getElementById('auth-control');
  if (!container) return;

  const principal = currentPrincipal();
  container.innerHTML = '';

  if (principal) {
    // Signed in: show principal name, role, and sign-out button.
    const div = document.createElement('div');
    div.className = 'auth-signed-in';
    div.innerHTML = `
      <span class="principal-name">${escapeHtml(principal.name)}</span>
      <span class="principal-role">(${escapeHtml(principal.role)})</span>
      <button id="sign-out-btn" class="btn-sign-out">Sign out</button>
    `;
    container.appendChild(div);

    const signOutBtn = div.querySelector('#sign-out-btn');
    signOutBtn.addEventListener('click', async () => {
      await signOut();
    });

    // Show admin link if administrator.
    const adminLink = document.getElementById('admin-keys-link');
    if (adminLink) {
      adminLink.style.display = 'inline-block';
    }
  } else {
    // Signed out: show authenticate button.
    const div = document.createElement('div');
    div.className = 'auth-signed-out';
    div.innerHTML = `<button id="authenticate-btn" class="btn-authenticate">Authenticate</button>`;
    container.appendChild(div);

    const authenticateBtn = div.querySelector('#authenticate-btn');
    authenticateBtn.addEventListener('click', () => {
      const dialog = document.getElementById('sign-in-dialog');
      if (dialog) dialog.showModal();
    });

    // Hide admin link if not administrator.
    const adminLink = document.getElementById('admin-keys-link');
    if (adminLink) {
      adminLink.style.display = 'none';
    }
  }
}

/**
 * Set up the sign-in dialog on page load.
 */
function initSignInDialog() {
  const dialog = document.getElementById('sign-in-dialog');
  const form = document.getElementById('sign-in-form');
  const keyInput = document.getElementById('sign-in-key');
  const errorDiv = document.getElementById('sign-in-error');
  const submitBtn = document.querySelector('#sign-in-form button[type="submit"]');

  if (!form || !keyInput) return;

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (errorDiv) errorDiv.style.display = 'none';
    submitBtn.disabled = true;

    const key = keyInput.value;
    const result = await signIn(key);

    if (result.ok) {
      keyInput.value = '';
      if (dialog) dialog.close();
    } else {
      if (errorDiv) {
        errorDiv.textContent = result.error || 'Authentication failed';
        errorDiv.style.display = 'block';
      }

      // On rate limit, disable submit for Retry-After duration.
      if (result.retryAfter) {
        const seconds = result.retryAfter;
        submitBtn.disabled = true;
        let remaining = seconds;
        const updateCountdown = () => {
          if (remaining > 0) {
            submitBtn.textContent = `Try again in ${remaining}s`;
            remaining--;
            setTimeout(updateCountdown, 1000);
          } else {
            submitBtn.textContent = 'Authenticate';
            submitBtn.disabled = false;
          }
        };
        updateCountdown();
      } else {
        submitBtn.disabled = false;
      }
    }
  });

  // Close dialog on escape or close button.
  if (dialog) {
    dialog.addEventListener('close', () => {
      keyInput.value = '';
      if (errorDiv) errorDiv.style.display = 'none';
      submitBtn.textContent = 'Authenticate';
      submitBtn.disabled = false;
    });
  }
}

/**
 * Escape HTML special characters to prevent XSS.
 * @param {string} text
 * @returns {string}
 */
function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

/**
 * Initialize the auth module on DOMContentLoaded.
 * Renders the header and sets up the sign-in dialog.
 */
document.addEventListener('DOMContentLoaded', () => {
  renderAuthHeader();
  initSignInDialog();
});
