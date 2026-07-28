"""Sample AI model listing data.

This module is the seed source of truth for the application database. New
installs are populated from ``SAMPLE_MODELS`` via ``flask seed``.

Public symbol:
    SAMPLE_MODELS: list[dict] - 22 AI models with pricing, context window,
    and modality information as per the home-page mockup.

Record shape:
    name            str        "vendor/model-slug", unique identifier.
    price_in        float      USD per 1M input tokens.
    price_out       float      USD per 1M output tokens.
    context_tokens  int        Raw context window size in tokens.
    input_content   list[str]  Input modalities.
    output_content  list[str]   Output modalities.

Modalities used in this dataset: Text, Images, Files, Videos, Audio.
"""

SAMPLE_MODELS: list[dict] = [
    {
        "name": "anthropic/claude-haiku-4.5",
        "price_in": 1.00,
        "price_out": 5.00,
        "context_tokens": 200_000,
        "input_content": ["Text", "Images", "Files"],
        "output_content": ["Text"],
    },
    {
        "name": "anthropic/claude-opus-4.8",
        "price_in": 5.00,
        "price_out": 25.00,
        "context_tokens": 1_000_000,
        "input_content": ["Text", "Images", "Files"],
        "output_content": ["Text"],
    },
    {
        "name": "anthropic/claude-sonnet-5",
        "price_in": 2.00,
        "price_out": 10.00,
        "context_tokens": 1_000_000,
        "input_content": ["Text", "Images", "Files"],
        "output_content": ["Text"],
    },
    {
        "name": "deepseek/deepseek-v4-flash",
        "price_in": 0.09,
        "price_out": 0.18,
        "context_tokens": 1_000_000,
        "input_content": ["Text"],
        "output_content": ["Text"],
    },
    {
        "name": "deepseek/deepseek-v4-pro",
        "price_in": 0.44,
        "price_out": 0.87,
        "context_tokens": 1_000_000,
        "input_content": ["Text"],
        "output_content": ["Text"],
    },
    {
        "name": "google/gemini-2.5-flash-lite",
        "price_in": 0.10,
        "price_out": 0.40,
        "context_tokens": 1_000_000,
        "input_content": ["Text", "Images", "Files", "Videos", "Audio"],
        "output_content": ["Text"],
    },
    {
        "name": "google/gemini-3.1-flash-lite",
        "price_in": 0.25,
        "price_out": 1.50,
        "context_tokens": 1_000_000,
        "input_content": ["Text", "Images", "Files", "Videos", "Audio"],
        "output_content": ["Text"],
    },
    {
        "name": "google/gemini-3.1-flash-lite-image",
        "price_in": 0.25,
        "price_out": 1.50,
        "context_tokens": 66_000,
        "input_content": ["Text", "Images"],
        "output_content": ["Text", "Images"],
    },
    {
        "name": "google/gemini-3.5-flash",
        "price_in": 1.50,
        "price_out": 9.00,
        "context_tokens": 1_000_000,
        "input_content": ["Text", "Images", "Videos", "Files", "Audio"],
        "output_content": ["Text"],
    },
    {
        "name": "google/gemini-3.5-flash-lite",
        "price_in": 0.30,
        "price_out": 2.50,
        "context_tokens": 1_000_000,
        "input_content": ["Text", "Images", "Files", "Videos", "Audio"],
        "output_content": ["Text"],
    },
    {
        "name": "google/gemini-3.6-flash",
        "price_in": 1.50,
        "price_out": 7.50,
        "context_tokens": 1_000_000,
        "input_content": ["Text", "Images", "Files", "Videos", "Audio"],
        "output_content": ["Text"],
    },
    {
        "name": "minimax/minimax-m3",
        "price_in": 0.30,
        "price_out": 1.20,
        "context_tokens": 1_000_000,
        "input_content": ["Text", "Images", "Videos"],
        "output_content": ["Text"],
    },
    {
        "name": "moonshotai/kimi-k2.6",
        "price_in": 0.66,
        "price_out": 3.41,
        "context_tokens": 262_000,
        "input_content": ["Text", "Images"],
        "output_content": ["Text"],
    },
    {
        "name": "moonshotai/kimi-k2.7-code",
        "price_in": 0.72,
        "price_out": 3.50,
        "context_tokens": 262_000,
        "input_content": ["Text", "Images"],
        "output_content": ["Text"],
    },
    {
        "name": "moonshotai/kimi-k3",
        "price_in": 3.00,
        "price_out": 15.00,
        "context_tokens": 1_000_000,
        "input_content": ["Text", "Images"],
        "output_content": ["Text"],
    },
    {
        "name": "openai/gpt-5.5",
        "price_in": 5.00,
        "price_out": 30.00,
        "context_tokens": 1_000_000,
        "input_content": ["Text", "Images", "Files"],
        "output_content": ["Text"],
    },
    {
        "name": "openai/gpt-5.6-luna-pro",
        "price_in": 1.00,
        "price_out": 6.00,
        "context_tokens": 1_000_000,
        "input_content": ["Text", "Images", "Files"],
        "output_content": ["Text"],
    },
    {
        "name": "openai/gpt-5.6-sol-pro",
        "price_in": 5.00,
        "price_out": 30.00,
        "context_tokens": 1_000_000,
        "input_content": ["Text", "Images", "Files"],
        "output_content": ["Text"],
    },
    {
        "name": "openai/gpt-5.6-terra-pro",
        "price_in": 2.50,
        "price_out": 15.00,
        "context_tokens": 1_000_000,
        "input_content": ["Text", "Images", "Files"],
        "output_content": ["Text"],
    },
    {
        "name": "qwen/qwen3.7-max",
        "price_in": 1.48,
        "price_out": 4.43,
        "context_tokens": 1_000_000,
        "input_content": ["Text"],
        "output_content": ["Text"],
    },
    {
        "name": "qwen/qwen3.7-plus",
        "price_in": 0.32,
        "price_out": 1.28,
        "context_tokens": 1_000_000,
        "input_content": ["Text", "Images"],
        "output_content": ["Text"],
    },
    {
        "name": "z-ai/glm-5.2",
        "price_in": 0.93,
        "price_out": 3.00,
        "context_tokens": 1_000_000,
        "input_content": ["Text"],
        "output_content": ["Text"],
    },
]
