/**
 * Administrator model-creation form and edit dialog.
 *
 * Two forms share this page:
 *   - Create (#create-model-form): administrator-only; gated by isAdministrator() in auth.js
 *   - Edit   (#edit-model-form):   updater-or-administrator; opens in a <dialog>
 *
 * The two forms use distinct checkbox `name` attributes (`input-content` for
 * create, `edit-input-content` for edit) because `getCheckedValues` queries
 * checkboxes globally by name.
 */
document.addEventListener('DOMContentLoaded', () => {
  const createForm = document.getElementById('create-model-form');
  const editForm = document.getElementById('edit-model-form');
  const editDialog = document.getElementById('edit-model-dialog');
  const createMessage = document.getElementById('create-model-message');
  const editMessage = document.getElementById('edit-model-message');
  const createSection = document.getElementById('create-model-section');

  // Reveal the create section only for administrators. Edit controls remain
  // visible to both roles per D-012; the server gate stays the authority.
  if (createSection && typeof isAdministrator === 'function' && isAdministrator()) {
    createSection.hidden = false;
  }

  /**
   * Get checked modality values for a fieldset by its checkbox name.
   * @param {string} fieldName
   * @returns {string[]}
   */
  function getCheckedValues(fieldName) {
    return [...document.querySelectorAll(`input[name="${fieldName}"]:checked`)].map((input) => input.value);
  }

  /**
   * Parse a CSV data attribute into a trimmed string list (drops empties).
   */
  function parseCsvAttr(value) {
    if (!value) return [];
    return value.split(',').map((s) => s.trim()).filter(Boolean);
  }

  /**
   * Show or hide a message box.
   */
  function showMessage(el, text, isSuccess = false) {
    if (!el) return;
    el.textContent = text;
    el.className = isSuccess ? 'message-box success-message' : 'message-box error-message';
    el.hidden = false;
  }

  function hideMessage(el) {
    if (!el) return;
    el.hidden = true;
  }

  function setCheckedByName(fieldName, values) {
    const wanted = new Set(values);
    document.querySelectorAll(`input[name="${fieldName}"]`).forEach((input) => {
      input.checked = wanted.has(input.value);
    });
  }

  // ----- Create form (administrator-only) -----
  if (createForm) {
    createForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      hideMessage(createMessage);

      const name = document.getElementById('model-name').value.trim();
      const priceInStr = document.getElementById('model-price-in').value;
      const priceOutStr = document.getElementById('model-price-out').value;
      const contextStr = document.getElementById('model-context').value;
      const inputContent = getCheckedValues('input-content');
      const outputContent = getCheckedValues('output-content');

      const requiredFields = [
        ['Model name', name],
        ['Price in', priceInStr],
        ['Price out', priceOutStr],
        ['Context tokens', contextStr],
        ['Input content modalities', inputContent],
        ['Output content modalities', outputContent],
      ];
      const missingField = requiredFields.find(([, value]) =>
        Array.isArray(value) ? value.length === 0 : value === ''
      );
      if (missingField) {
        showMessage(createMessage, `${missingField[0]} is required.`);
        return;
      }

      const payload = {
        name,
        price_in: Number(priceInStr),
        price_out: Number(priceOutStr),
        context_tokens: Number(contextStr),
        input_content: inputContent,
        output_content: outputContent,
      };

      const response = await authFetch('/admin/models', {
        method: 'POST',
        body: payload,
      });

      if (response.status === 201) {
        createForm.reset();
        showMessage(createMessage, 'Model added successfully.', true);
        // Reload to pick up the new row in the table.
        window.location.reload();
      } else {
        const data = await response.json().catch(() => ({}));
        showMessage(createMessage, data.error || 'Failed to add model.');
      }
    });
  }

  // ----- Edit dialog wiring -----
  if (editDialog && editForm) {
    const editName = document.getElementById('edit-model-name');
    const editPriceIn = document.getElementById('edit-model-price-in');
    const editPriceOut = document.getElementById('edit-model-price-out');
    const editContext = document.getElementById('edit-model-context');
    let activeModelId = null;

    function openEditDialog(row) {
      activeModelId = row.dataset.modelId;
      editName.value = row.dataset.modelName || '';
      editPriceIn.value = row.dataset.priceIn || '';
      editPriceOut.value = row.dataset.priceOut || '';
      editContext.value = row.dataset.contextTokens || '';
      setCheckedByName('edit-input-content', parseCsvAttr(row.dataset.inputContent));
      setCheckedByName('edit-output-content', parseCsvAttr(row.dataset.outputContent));
      hideMessage(editMessage);
      if (typeof editDialog.showModal === 'function') {
        editDialog.showModal();
      } else {
        editDialog.setAttribute('open', 'open');
      }
    }

    document.querySelectorAll('.js-edit-model').forEach((button) => {
      button.addEventListener('click', () => {
        const row = button.closest('tr[data-model-id]');
        if (row) openEditDialog(row);
      });
    });

    editDialog.querySelectorAll('[data-action="cancel-edit"]').forEach((el) => {
      el.addEventListener('click', () => editDialog.close());
    });

    editForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      hideMessage(editMessage);

      if (!activeModelId) {
        showMessage(editMessage, 'No model selected.');
        return;
      }

      const priceInStr = editPriceIn.value;
      const priceOutStr = editPriceOut.value;
      const contextStr = editContext.value;
      const inputContent = getCheckedValues('edit-input-content');
      const outputContent = getCheckedValues('edit-output-content');

      const requiredFields = [
        ['Price in', priceInStr],
        ['Price out', priceOutStr],
        ['Context tokens', contextStr],
        ['Input content modalities', inputContent],
        ['Output content modalities', outputContent],
      ];
      const missingField = requiredFields.find(([, value]) =>
        Array.isArray(value) ? value.length === 0 : value === ''
      );
      if (missingField) {
        showMessage(editMessage, `${missingField[0]} is required.`);
        return;
      }

      const payload = {
        price_in: Number(priceInStr),
        price_out: Number(priceOutStr),
        context_tokens: Number(contextStr),
        input_content: inputContent,
        output_content: outputContent,
      };

      const response = await authFetch(`/admin/models/${activeModelId}`, {
        method: 'PATCH',
        body: payload,
      });

      if (response.ok) {
        editDialog.close();
        window.location.reload();
      } else {
        const data = await response.json().catch(() => ({}));
        showMessage(editMessage, data.error || 'Failed to update model.');
      }
    });
  }
});
