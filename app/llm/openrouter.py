import os
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["OPENROUTER_API_KEY"],
    base_url=os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
)

MODEL = os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")


def stream_reply(system_prompt: str, history: list[dict]):
    """Yields text chunks as they arrive from the model."""
    stream = client.chat.completions.create(
        model=MODEL,
        stream=True,
        messages=[{"role": "system", "content": system_prompt}, *history],
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta
