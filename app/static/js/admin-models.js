/**
 * Administrator model-creation form and edit dialog.
 *
 * Two forms share this page:
 *   - Create (#create-model-form): administrator-only; gated by isAdministrator() in auth.js
 *   - Edit   (#edit-model-form):   updater-or-administrator; opens in a <dialog>
 *
 * Output-only / context-type semantics (D-037..D-039):
 *   - `price_in` blank means NOT applicable and is sent as JSON `null`;
 *     typing `0` is a distinct free-input price. Never `Number('') === 0`.
 *   - `context_type` (`tokens`|`image`) and `pricing_unit`
 *     (`million_tokens`|`image`) are closed vocabularies sent verbatim.
 *   - An `image` context carries no numeric `context_tokens`; the field is
 *     disabled and sends `null`. `tokens` context requires a positive count.
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

  // ----- Hide/Unhide toggle (administrator-only, D-019) -----
  // The server is the real authority; this client-side gate is cosmetic.
  // Buttons are rendered hidden and revealed only for administrators, matching
  // the create-section pattern above. Hide never blocks an updater value sync
  // (D-023), so the edit control stays visible on hidden rows for both roles.
  const toggleMessage = document.getElementById('toggle-models-message');
  const showToggleMessage = (text, isSuccess = false) => {
    if (!toggleMessage) return;
    toggleMessage.textContent = text;
    toggleMessage.className = isSuccess ? 'message-box success-message' : 'message-box error-message';
    toggleMessage.hidden = false;
  };

  document.querySelectorAll('.js-toggle-hidden').forEach((button) => {
    button.addEventListener('click', async () => {
      const row = button.closest('tr[data-model-id]');
      if (!row) return;
      const modelId = row.dataset.modelId;
      const current = row.dataset.hidden === 'true';
      const nextHidden = !current;
      const label = nextHidden ? 'hidden' : 'visible';

      if (toggleMessage) toggleMessage.hidden = true;

      const response = await authFetch(`/admin/models/${modelId}/hidden`, {
        method: 'PUT',
        body: { hidden: nextHidden },
      });

      if (response.ok) {
        // Reload to reflect the new hidden state server-side. The page's
        // established write idiom is a full reload (D-016: no client-side
        // view state anywhere in this repo), so we do not mutate the row.
        window.location.reload();
      } else {
        const data = await response.json().catch(() => ({}));
        showToggleMessage(data.error || `Failed to mark model ${label}.`);
      }
    });
  });

  if (typeof isAdministrator === 'function' && isAdministrator()) {
    document.querySelectorAll('.js-toggle-hidden').forEach((button) => {
      button.hidden = false;
    });
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

  /**
   * Toggle a context-tokens input's enabled state to match the selected
   * context type. `image` disables and clears the field (it sends null);
   * `tokens` re-enables it.
   */
  function syncContextField(contextSelect, contextInput) {
    if (!contextSelect || !contextInput) return;
    const isImage = contextSelect.value === 'image';
    contextInput.disabled = isImage;
    if (isImage) {
      contextInput.value = '';
    }
  }

  function wireContextField(contextSelect, contextInput) {
    if (!contextSelect || !contextInput) return;
    contextSelect.addEventListener('change', () => syncContextField(contextSelect, contextInput));
    syncContextField(contextSelect, contextInput);
  }

  /**
   * Build the editable model payload. `priceInStr` blank -> null (not
   * applicable); `0` stays a real free-input price. Image context sends
   * `context_tokens: null`.
   */
  function buildModelPayload({ priceInStr, priceOutStr, contextType, contextStr, pricingUnit, inputContent, outputContent }) {
    return {
      price_in: priceInStr === '' ? null : Number(priceInStr),
      price_out: Number(priceOutStr),
      context_type: contextType,
      context_tokens: contextType === 'image' ? null : Number(contextStr),
      pricing_unit: pricingUnit,
      input_content: inputContent,
      output_content: outputContent,
    };
  }

  // ----- Create form (administrator-only) -----
  if (createForm) {
    const createContextType = document.getElementById('model-context-type');
    const createContextInput = document.getElementById('model-context');
    wireContextField(createContextType, createContextInput);

    createForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      hideMessage(createMessage);

      const name = document.getElementById('model-name').value.trim();
      const priceInStr = document.getElementById('model-price-in').value;
      const priceOutStr = document.getElementById('model-price-out').value;
      const contextType = createContextType.value;
      const contextStr = createContextInput.value;
      const pricingUnit = document.getElementById('model-pricing-unit').value;
      const inputContent = getCheckedValues('input-content');
      const outputContent = getCheckedValues('output-content');

      const requiredFields = [
        ['Model name', name],
        ['Price out', priceOutStr],
        ['Input content modalities', inputContent],
        ['Output content modalities', outputContent],
      ];
      if (contextType === 'tokens') {
        requiredFields.push(['Context tokens', contextStr]);
      }
      const missingField = requiredFields.find(([, value]) =>
        Array.isArray(value) ? value.length === 0 : value === ''
      );
      if (missingField) {
        showMessage(createMessage, `${missingField[0]} is required.`);
        return;
      }

      const payload = {
        name,
        ...buildModelPayload({
          priceInStr,
          priceOutStr,
          contextType,
          contextStr,
          pricingUnit,
          inputContent,
          outputContent,
        }),
      };

      const response = await authFetch('/admin/models', {
        method: 'POST',
        body: payload,
      });

      if (response.status === 201) {
        createForm.reset();
        syncContextField(createContextType, createContextInput);
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
    const editContextType = document.getElementById('edit-model-context-type');
    const editContext = document.getElementById('edit-model-context');
    const editPricingUnit = document.getElementById('edit-model-pricing-unit');
    let activeModelId = null;

    wireContextField(editContextType, editContext);

    function openEditDialog(row) {
      activeModelId = row.dataset.modelId;
      editName.value = row.dataset.modelName || '';
      editPriceIn.value = row.dataset.priceIn || '';
      editPriceOut.value = row.dataset.priceOut || '';
      editContextType.value = row.dataset.contextType || 'tokens';
      editContext.value = row.dataset.contextTokens || '';
      editPricingUnit.value = row.dataset.pricingUnit || 'million_tokens';
      setCheckedByName('edit-input-content', parseCsvAttr(row.dataset.inputContent));
      setCheckedByName('edit-output-content', parseCsvAttr(row.dataset.outputContent));
      syncContextField(editContextType, editContext);
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
      const contextType = editContextType.value;
      const contextStr = editContext.value;
      const pricingUnit = editPricingUnit.value;
      const inputContent = getCheckedValues('edit-input-content');
      const outputContent = getCheckedValues('edit-output-content');

      const requiredFields = [
        ['Price out', priceOutStr],
        ['Input content modalities', inputContent],
        ['Output content modalities', outputContent],
      ];
      if (contextType === 'tokens') {
        requiredFields.push(['Context tokens', contextStr]);
      }
      const missingField = requiredFields.find(([, value]) =>
        Array.isArray(value) ? value.length === 0 : value === ''
      );
      if (missingField) {
        showMessage(editMessage, `${missingField[0]} is required.`);
        return;
      }

      const payload = buildModelPayload({
        priceInStr,
        priceOutStr,
        contextType,
        contextStr,
        pricingUnit,
        inputContent,
        outputContent,
      });

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
