"""Small, lazy, configurable text client for lore; all calls use the existing TFY gateway."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests
from dotenv import dotenv_values

DEFAULT_MODEL = "openai-group/gpt-6-astra"
DEFAULT_CHOICE_MODEL = "openai-group/gpt-6-sol"


def model_slug(value: str) -> str:
    if "/" in value:
        return value
    if value.startswith("gpt-"):
        return "openai-group/" + value
    if value.startswith("claude-"):
        return "claude-group/" + value
    raise ValueError("Use a gateway model slug, e.g. openai-group/gpt-6-astra")


class LoreClient:
    def __init__(self, model: str = DEFAULT_MODEL, review_model: str | None = None,
                 reasoning: str = "high", trace_dir: Path | None = None,
                 choice_model: str = DEFAULT_CHOICE_MODEL, choice_reasoning: str = "medium"):
        self.model = model_slug(model)
        self.review_model = model_slug(review_model or model)
        self.reasoning = reasoning
        self.choice_model = model_slug(choice_model)
        self.choice_reasoning = choice_reasoning
        self.trace_dir = trace_dir
        self.calls: list[dict] = []
        # No credentials or network activity at module import / CLI --list time.
        env = {**dotenv_values(Path(__file__).resolve().parents[2] / ".env"), **os.environ}
        self.base_url = str(env.get("TFY_BASE_URL") or "").rstrip("/")
        key = env.get("TFY_API_KEY")
        if not self.base_url or not key:
            raise ValueError("Lore generation requires TFY_BASE_URL and TFY_API_KEY")
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {key}", "x-tfy-api-key": key})

    def __call__(self, system: str, user: str, tag: str, max_tokens: int = 12000) -> str:
        model = self.choice_model if tag == "hook-choice" else self.review_model if tag == "review" else self.model
        reasoning = self.choice_reasoning if tag == "hook-choice" else self.reasoning
        payload = {"model": model, "messages": [
            {"role": "system", "content": system}, {"role": "user", "content": user}]}
        if model.startswith("openai-group/gpt-"):
            payload.update(reasoning_effort=reasoning, max_completion_tokens=max_tokens)
        else:
            payload["max_tokens"] = max_tokens
        # No temperature with reasoning; no tools require the Responses endpoint here.
        for attempt in range(2):
            started = time.monotonic()
            record = {"tag": tag, "attempt": attempt + 1, "request": payload}
            try:
                response = self.session.post(self.base_url + "/chat/completions", json=payload,
                                             timeout=(15, 360))
                record["http_status"] = response.status_code
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt == 0:
                        record["error"] = "transient_gateway_error"
                        time.sleep(2)
                        continue
                if not response.ok:
                    raise RuntimeError(f"Lore gateway returned HTTP {response.status_code} for {model}")
                data = response.json()
                choice = data["choices"][0]
                record.update(response=choice, usage=data.get("usage", {}),
                              response_model=data.get("model"))
                reason = choice.get("finish_reason")
                if reason != "stop":
                    raise RuntimeError(f"Incomplete lore response: {tag}, finish_reason={reason!r}")
                raw = choice["message"].get("content")
                if not isinstance(raw, str) or not raw.strip():
                    raise RuntimeError(f"Empty lore response: {tag} from {model}")
                return raw.strip()
            except (requests.Timeout, requests.ConnectionError) as exc:
                record["error"] = type(exc).__name__
                if attempt:
                    raise RuntimeError(f"Lore gateway connection failed for {tag}") from None
                time.sleep(2)
            except Exception as exc:
                record["error"] = type(exc).__name__
                raise
            finally:
                record["seconds"] = round(time.monotonic() - started, 2)
                self.calls.append(record)
                if self.trace_dir:
                    self.trace_dir.mkdir(parents=True, exist_ok=True)
                    name = f"{len(self.calls):03d}-{tag}.json"
                    (self.trace_dir / name).write_text(json.dumps(record, ensure_ascii=False, indent=2),
                                                      encoding="utf-8")
        raise RuntimeError(f"No completion for {tag}")

    def provenance(self) -> dict:
        return {"model": self.model, "review_model": self.review_model, "reasoning": self.reasoning,
                "choice_model": self.choice_model, "choice_reasoning": self.choice_reasoning,
                "calls": len(self.calls),
                "usage": {key: sum(c.get("usage", {}).get(key, 0) or 0 for c in self.calls)
                          for key in ("prompt_tokens", "completion_tokens", "total_tokens", "costInUSD")}}
