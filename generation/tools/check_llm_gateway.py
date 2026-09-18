#!/usr/bin/env python3
"""Assert the TrueFoundry routing in core/clients/openai.py with both vendor SDKs faked. Needs no credentials."""

from __future__ import annotations

import ast
import logging
import os
import sys
import tempfile
import warnings
from pathlib import Path
from types import SimpleNamespace

GENERATION = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(GENERATION))

# Both must be set before the first core import: core/clients/openai.py captures them into
# module constants at import, and load_dotenv does not override what is already set.
os.environ["TFY_API_KEY"] = "test-dummy-tfy-key"
os.environ["TFY_BASE_URL"] = "https://tfy.example.invalid"

from core.clients import openai as llm  # noqa: E402
from core.pricing import gpt4_cost  # noqa: E402

CALLS: list[tuple[str, dict]] = []
FAIL_NEXT_OPENAI = [False]

SYSTEM = {"role": "system", "content": "you are a historian"}
USER = {"role": "user", "content": "name one cause of the Stamp Act protests"}


class FakeOpenAI:
    """Stands in for openai.OpenAI, recording construction and request kwargs."""

    def __init__(self, **kwargs):
        CALLS.append(("openai-client", kwargs))
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        CALLS.append(("openai-create", kwargs))
        if FAIL_NEXT_OPENAI[0]:
            FAIL_NEXT_OPENAI[0] = False
            raise RuntimeError("invalid image url")
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="openai text"))],
            usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7),
        )


class FakeAnthropic:
    """Stands in for anthropic.Anthropic, recording construction and request kwargs."""

    def __init__(self, **kwargs):
        CALLS.append(("anthropic-client", kwargs))
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        CALLS.append(("anthropic-create", kwargs))
        # A thinking block ahead of the text one, because that is what the text extraction
        # has to skip past on the reasoning tiers.
        return SimpleNamespace(content=[SimpleNamespace(type="thinking", text=""),
                                        SimpleNamespace(type="text", text="claude text")])


class FakeFetch:
    """Stands in for a requests.get of an image the gateway refused."""

    content = b"\x89PNG"

    def raise_for_status(self):
        pass


def install() -> None:
    """Point the module at the fakes and away from the working directory."""
    llm.openai.OpenAI = FakeOpenAI
    llm.anthropic.Anthropic = FakeAnthropic
    llm.requests.get = lambda url: FakeFetch()
    # The vision case fails a call on purpose, and the client logs that with a traceback.
    llm.logger.setLevel(logging.CRITICAL)
    # log_llm_message appends every prompt to ./prompts.txt, which is not this repo's problem.
    os.chdir(tempfile.mkdtemp(prefix="check_llm_gateway_"))


def only(kind: str) -> dict:
    """The kwargs of the single recorded call of one kind, asserting there was exactly one."""
    matches = [kwargs for name, kwargs in CALLS if name == kind]
    assert len(matches) == 1, f"expected 1 {kind} call, got {len(matches)}"
    return matches[0]


def check_openai_route():
    CALLS.clear()
    costs = []
    response = llm.chat_complete([SYSTEM, USER], llm.LLM.GPT_5, temperature=0.7, max_tokens=4000,
                                 cost_callback=lambda prompt, completion: costs.append((prompt, completion)))

    assert response == "openai text", response
    client, create = only("openai-client"), only("openai-create")
    assert client == {"api_key": "test-dummy-tfy-key",
                      "base_url": "https://tfy.example.invalid"}, client
    assert create["model"] == "openai-group/gpt-5.5", create["model"]
    # The system message rides along as-is: this route is OpenAI-shaped end to end.
    assert create["messages"] == [SYSTEM, USER], create["messages"]
    # Neither knob may reach a reasoning model, whatever the caller asked for.
    assert "temperature" not in create and "max_tokens" not in create, create
    assert costs == [gpt4_cost(11, 7)], costs
    assert not any(name.startswith("anthropic") for name, _ in CALLS), "Claude route was used"
    print("  openai     gpt-5.5 slug, gateway key and base_url, no temperature, cost reported")


def check_claude_route():
    CALLS.clear()
    response = llm.chat_complete([SYSTEM, USER], llm.LLM.CLAUDE_5_OPUS, max_tokens=1234)

    assert response == "claude text", response
    client, create = only("anthropic-client"), only("anthropic-create")
    assert client["base_url"] == "https://tfy.example.invalid", client
    # The gateway authenticates on its own header here, so the SDK's api_key is a placeholder.
    assert client["default_headers"] == {"x-tfy-api-key": "test-dummy-tfy-key"}, client
    assert client["api_key"] != "test-dummy-tfy-key", client
    assert create["model"] == "claude-group/claude-opus-5", create["model"]
    assert create["max_tokens"] == 1234, create["max_tokens"]
    assert create["system"] == "you are a historian", create["system"]
    assert create["messages"] == [USER], create["messages"]
    assert not any(name.startswith("openai") for name, _ in CALLS), "OpenAI route was used"
    print("  claude     opus-5 slug, x-tfy-api-key header, system split out of messages")


def check_blank_system_dropped():
    CALLS.clear()
    # core/helpers.py::llm_call is called with system_prompt='' all over the stages, and
    # Anthropic refuses a blank system, so it has to be absent rather than empty.
    llm.chat_complete([{"role": "system", "content": ""}, USER], llm.LLM.CLAUDE_5_SONNET)
    assert "system" not in only("anthropic-create"), only("anthropic-create")

    CALLS.clear()
    llm.chat_complete([USER], llm.LLM.CLAUDE_5_SONNET)
    assert "system" not in only("anthropic-create"), only("anthropic-create")
    # An unspecified cap is the vendor ceiling, not the 4000 llm_complete defaults to.
    assert only("anthropic-create")["max_tokens"] == 50000, only("anthropic-create")
    print("  claude     blank and absent system prompts both omitted, cap defaults to 50000")


def check_vision_route():
    CALLS.clear()
    messages = [{"role": "system", "content": "is the image visible?"},
                llm.openai_gpt4v_message("https://example.invalid/map.png", 0)]
    FAIL_NEXT_OPENAI[0] = True

    assert llm.call_openai_vision(messages) == "openai text"

    creates = [kwargs for name, kwargs in CALLS if name == "openai-create"]
    assert len(creates) == 2, f"the data-URI retry did not happen: {len(creates)} calls"
    assert all(c["model"] == "openai-group/gpt-5.5" for c in creates), creates
    url = messages[1]["content"][1]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,"), url
    print("  vision     gateway slug on both attempts, refused image inlined as a data URI")


def check_fail_closed():
    # The direct-upload Gemini member is deliberately unmapped: core/clients/gemini.py owns it.
    for model in ("nonexistent-model", llm.LLM.GEMINI_2_5):
        try:
            llm.gateway_slug(model)
            raise AssertionError(f"{model} should not resolve to a slug")
        except ValueError as error:
            assert "No TrueFoundry gateway mapping" in str(error), str(error)

    # llm_complete swallows every other exception and returns None. A config error must not
    # take that path, or a keyless run looks like a model that had nothing to say.
    try:
        llm.llm_complete([USER], llm.LLM.GEMINI_2_5)
        raise AssertionError("llm_complete returned instead of raising on an unmapped model")
    except ValueError:
        pass

    # Both entry points are retried, and a config error must reach the caller as itself
    # rather than as the RetryError three attempts would otherwise wrap it in.
    try:
        llm.chat_complete([USER], "nonexistent-model")
        raise AssertionError("chat_complete accepted an unmapped model")
    except ValueError:
        pass

    original = llm.TFY_API_KEY
    try:
        llm.TFY_API_KEY = None
        try:
            llm.gateway_slug(llm.LLM.GPT_5)
            raise AssertionError("a mapped model resolved with no gateway key")
        except ValueError as error:
            assert "TFY_API_KEY" in str(error), str(error)
    finally:
        llm.TFY_API_KEY = original
    print("  refusals   unmapped model and missing key both raise, and llm_complete re-raises")


def check_catalog():
    unmapped = [m.name for m in llm.LLM
                if m is not llm.LLM.GEMINI_2_5 and m.value not in llm.GATEWAY_MODEL_SLUGS]
    assert not unmapped, f"LLM members with no gateway slug: {unmapped}"
    for value, slug in llm.GATEWAY_MODEL_SLUGS.items():
        assert slug.count("/") == 1 and slug.split("/")[0].endswith("-group"), (value, slug)
    print(f"  catalogue  {len(llm.GATEWAY_MODEL_SLUGS)} models mapped, every slug vendor-prefixed")


def check_call_sites():
    """Every LLM.MEMBER named anywhere in generation/ has to exist, or a stage dies mid-run."""
    skip = {"__pycache__", "site-packages", ".venv", "venv", "env", ".tox"}
    named: dict[str, list[str]] = {}
    for path in sorted(p for p in GENERATION.rglob("*.py") if not skip & set(p.parts)):
        with warnings.catch_warnings():
            # A few prompt files carry regex-ish escapes that parse fine and warn loudly.
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                    and node.value.id == "LLM"):
                named.setdefault(node.attr, []).append(f"{path.relative_to(GENERATION)}:{node.lineno}")

    unknown = {name: where for name, where in named.items() if name not in llm.LLM.__members__}
    assert not unknown, f"references to LLM members that do not exist: {unknown}"
    print(f"  call sites {sum(len(w) for w in named.values())} LLM references over "
          f"{len(named)} members, all defined")


def main() -> int:
    print("LLM gateway routing:")
    install()
    check_openai_route()
    check_claude_route()
    check_blank_system_dropped()
    check_vision_route()
    check_fail_closed()
    check_catalog()
    check_call_sites()
    print("\nAll gateway routing checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
