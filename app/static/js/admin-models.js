/**
 * Administrator model-creation form.
 * Validates that all optional fields are provided together.
 */
document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('create-model-form');
  if (!form) return;

  const messageBox = document.getElementById('model-form-message');

  /**
   * Get checked modality values for a fieldset.
   */
  function getCheckedValues(fieldName) {
    return [...document.querySelectorAll(`input[name="${fieldName}"]:checked`)].map((input) => input.value);
  }

  /**
   * Show a message (error or success).
   */
  function showMessage(text, isSuccess = false) {
    messageBox.textContent = text;
    messageBox.className = isSuccess ? 'message-box success-message' : 'message-box error-message';
    messageBox.hidden = false;
  }

  /**
   * Hide the message.
   */
  function hideMessage() {
    messageBox.hidden = true;
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    hideMessage();

    // Get all field values.
    const name = document.getElementById('model-name').value.trim();
    const priceInStr = document.getElementById('model-price-in').value;
    const priceOutStr = document.getElementById('model-price-out').value;
    const contextStr = document.getElementById('model-context').value;
    const inputContent = getCheckedValues('input-content');
    const outputContent = getCheckedValues('output-content');

    // Check: name is required
    if (!name) {
      showMessage('Model name is required.');
      return;
    }

    // Collect "supplied" optional fields (non-empty).
    const optionalFields = {
      price_in: priceInStr,
      price_out: priceOutStr,
      context_tokens: contextStr,
      input_content: inputContent,
      output_content: outputContent,
    };

    const supplied = Object.entries(optionalFields).filter(([, value]) => {
      if (Array.isArray(value)) return value.length > 0;
      return value !== '';
    });

    // All optional fields must be supplied together.
    if (supplied.length > 0 && supplied.length < Object.keys(optionalFields).length) {
      showMessage('Provide all optional model attributes, or leave all of them blank.');
      return;
    }

    // If nothing optional is supplied, error (all must be provided together).
    if (supplied.length === 0) {
      showMessage('Provide all optional model attributes.');
      return;
    }

    // Build payload.
    const payload = {
      name,
      price_in: Number(priceInStr),
      price_out: Number(priceOutStr),
      context_tokens: Number(contextStr),
      input_content: inputContent,
      output_content: outputContent,
    };

    // Send to server.
    const response = await authFetch('/admin/models', {
      method: 'POST',
      body: payload,
    });

    if (response.status === 201) {
      form.reset();
      showMessage('Model added successfully.', true);
    } else {
      const data = await response.json();
      showMessage(data.error || 'Failed to add model.');
    }
  });
});
