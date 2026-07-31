/**
 * Admin key management page behaviour.
 *
 * Loads keys from GET /admin/keys, displays them in a table with
 * create, revoke, and detail controls. All requests go through authFetch
 * so 401 is handled centrally by rendering "Administrator access required".
 */

/**
 * Format an ISO timestamp for display.
 * @param {string|null} isoString - ISO 8601 timestamp
 * @returns {string}
 */
function formatTimestamp(isoString) {
  if (!isoString) return '—';
  const date = new Date(isoString);
  return date.toLocaleString();
}

/**
 * Format ISO timestamp as a datetime-local input value.
 * @param {string|null} isoString
 * @returns {string}
 */
function formatDatetimeLocal(isoString) {
  if (!isoString) return '';
  const date = new Date(isoString);
  const year = date.getUTCFullYear();
  const month = String(date.getUTCMonth() + 1).padStart(2, '0');
  const day = String(date.getUTCDate()).padStart(2, '0');
  const hours = String(date.getUTCHours()).padStart(2, '0');
  const minutes = String(date.getUTCMinutes()).padStart(2, '0');
  return `${year}-${month}-${day}T${hours}:${minutes}`;
}

/**
 * Render the keys table or an error/access-required message.
 * @param {object} response - fetch response
 */
async function loadAndRenderKeys(response) {
  const container = document.getElementById('keys-container');
  if (!container) return;

  // Handle 401/403 (not authenticated / insufficient privilege).
  if (response.status === 401 || response.status === 403) {
    container.innerHTML = '<p class="error-message">Administrator access required.</p>';
    return;
  }

  if (!response.ok) {
    container.innerHTML = '<p class="error-message">Failed to load keys.</p>';
    return;
  }

  const data = await response.json();
  const keys = data.keys || [];

  if (keys.length === 0) {
    container.innerHTML = '<p class="empty-state">No keys created yet.</p>';
    return;
  }

  // Build the keys table.
  const table = document.createElement('table');
  table.className = 'keys-table';
  table.innerHTML = `
    <thead>
      <tr>
        <th scope="col">Name</th>
        <th scope="col">Role</th>
        <th scope="col">Status</th>
        <th scope="col">Created</th>
        <th scope="col">Last Used</th>
        <th scope="col">Expires</th>
        <th scope="col">Actions</th>
      </tr>
    </thead>
    <tbody></tbody>
  `;

  const tbody = table.querySelector('tbody');
  keys.forEach((key) => {
    const row = document.createElement('tr');
    row.innerHTML = `
      <td class="key-name">${escapeHtml(key.name)}</td>
      <td class="key-role">${escapeHtml(key.role)}</td>
      <td class="key-status"><span class="status-badge status-${key.status}">${escapeHtml(key.status)}</span></td>
      <td class="key-created">${formatTimestamp(key.created_at)}</td>
      <td class="key-last-used">${formatTimestamp(key.last_used_at)}</td>
      <td class="key-expires">${formatTimestamp(key.expires_at)}</td>
      <td class="key-actions">
        <button class="btn btn-sm btn-danger revoke-btn" data-kid="${escapeHtml(key.kid)}">Revoke</button>
      </td>
    `;

    // Attach revoke handler.
    const revokeBtn = row.querySelector('.revoke-btn');
    revokeBtn.addEventListener('click', () => revokeKey(key.kid, key.name));

    tbody.appendChild(row);
  });

  container.innerHTML = '';
  container.appendChild(table);
}

/**
 * Revoke a key by kid after confirmation.
 * @param {string} kid - key ID
 * @param {string} name - key name (for display)
 */
async function revokeKey(kid, name) {
  if (!confirm(`Revoke key "${escapeHtml(name)}"? This cannot be undone.`)) {
    return;
  }

  const response = await authFetch(`/admin/keys/${encodeURIComponent(kid)}`, {
    method: 'DELETE',
  });

  if (response.status === 409) {
    const data = await response.json();
    alert(data.error || 'Cannot revoke your own active key.');
  } else if (response.ok) {
    // Reload the keys table.
    await reloadKeys();
  } else {
    alert('Failed to revoke key.');
  }
}

/**
 * Reload the keys table from the server.
 */
async function reloadKeys() {
  const response = await authFetch('/admin/keys');
  await loadAndRenderKeys(response);
}

/**
 * Handle the create-key form submission.
 */
async function handleCreateKey(e) {
  e.preventDefault();

  const nameInput = document.getElementById('key-name');
  const roleSelect = document.getElementById('key-role');
  const expiresInput = document.getElementById('key-expires');

  const name = nameInput.value.trim();
  const role = roleSelect.value;
  const expiresLocal = expiresInput.value;

  if (!name) {
    alert('Key name is required.');
    return;
  }

  // Convert datetime-local to ISO string.
  let expiresAt = null;
  if (expiresLocal) {
    const date = new Date(expiresLocal + ':00Z');
    expiresAt = date.toISOString();
  }

  const payload = { name, role };
  if (expiresAt) {
    payload.expires_at = expiresAt;
  }

  const response = await authFetch('/admin/keys', {
    method: 'POST',
    body: payload,
  });

  if (response.status === 201) {
    const data = await response.json();

    // Show the token once in a modal.
    document.getElementById('displayed-token').value = data.token;
    document.getElementById('token-display-dialog').showModal();

    // Clear the form and reload the table.
    nameInput.value = '';
    roleSelect.value = 'updater';
    expiresInput.value = '';
    await reloadKeys();
  } else {
    const data = await response.json();
    alert(data.error || 'Failed to create key.');
  }
}

/**
 * Copy displayed token to clipboard.
 */
function copyToClipboard() {
  const input = document.getElementById('displayed-token');
  input.select();
  document.execCommand('copy');
  // Briefly change button text to confirm copy.
  const btn = event.target;
  const originalText = btn.textContent;
  btn.textContent = 'Copied!';
  setTimeout(() => {
    btn.textContent = originalText;
  }, 2000);
}

/**
 * Escape HTML special characters.
 * @param {string} text
 * @returns {string}
 */
function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

/**
 * Initialize the admin keys page on DOMContentLoaded.
 */
document.addEventListener('DOMContentLoaded', async () => {
  // Load and render keys.
  const response = await authFetch('/admin/keys');
  await loadAndRenderKeys(response);

  // Set up create-key form.
  const form = document.getElementById('create-key-form');
  if (form) {
    form.addEventListener('submit', handleCreateKey);
  }
});
