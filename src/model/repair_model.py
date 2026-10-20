"""Model provider abstraction, robust output parser, and repair model orchestrator."""

import json
import os
import re
import time
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional

from src.analysis_engine.contracts import ErrorContext
from src.model.prompts import (
    build_feedback_prompt,
    build_few_shot_prompt,
    build_zero_shot_prompt,
)
from src.model.schemas import (
    FewShotExample,
    MLRepairCandidate,
    ModelOutputParseError,
    ProviderUnavailableError,
    RepairFeedback,
    StructuredModelOutput,
)


# ---------------------------------------------------------------- Provider Abstraction

class ModelProvider(ABC):
    """Abstract interface for LLM / code repair model backends."""

    @abstractmethod
    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        **kwargs,
    ) -> str:
        """Send prompt to the model and return the raw output text."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the backend is configured and callable."""
        pass

    @abstractmethod
    def get_model_name(self) -> str:
        """Return the model identifier string."""
        pass


class MockModelProvider(ModelProvider):
    """Deterministic, configurable mock backend for tests and offline execution.

    Can generate intelligent rule-based / heuristic repairs for standard test patterns,
    or be configured with preset responses, failure modes, or custom handlers.
    """

    def __init__(
        self,
        model_name: str = "mock-repair-v1",
        mode: str = "normal",
        custom_handler: Optional[Callable[[str, Optional[str]], str]] = None,
        response_queue: Optional[List[str]] = None,
    ):
        self.model_name = model_name
        self.mode = mode
        self.custom_handler = custom_handler
        self.response_queue = list(response_queue) if response_queue else []
        self.call_count = 0
        self.last_prompt: Optional[str] = None
        self.last_system_prompt: Optional[str] = None

    def is_available(self) -> bool:
        return True

    def get_model_name(self) -> str:
        return self.model_name

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        **kwargs,
    ) -> str:
        self.call_count += 1
        self.last_prompt = prompt
        self.last_system_prompt = system_prompt

        if self.custom_handler:
            return self.custom_handler(prompt, system_prompt)

        if self.response_queue:
            return self.response_queue.pop(0)

        if self.mode == "timeout":
            raise ProviderUnavailableError("Simulated mock timeout after 5.0 seconds")

        if self.mode == "invalid_json":
            return "Here is your repair: ```json\n{ repaired_code: invalid_json, } \n```"

        if self.mode == "missing_code":
            return json.dumps({
                "repair_category": "syntax",
                "root_cause": "Removed colon",
                "target_line": 1,
                "confidence": 0.9,
            })

        if self.mode == "empty_code":
            return json.dumps({
                "repaired_code": "   ",
                "repair_category": "syntax",
                "root_cause": "Empty code output",
                "target_line": 1,
                "confidence": 0.1,
            })

        if self.mode == "excessive":
            return json.dumps({
                "repaired_code": "# Complete rewrite of entire file\ndef completely_new():\n    pass\n",
                "repair_category": "refactor",
                "root_cause": "Rewrote whole codebase",
                "target_line": 1,
                "confidence": 0.5,
            })

        if self.mode == "unchanged":
            # Extract raw code from prompt and return it unchanged
            match = re.search(r"Raw code without line numbers:\s*```(?:\w+)?\n(.*?)\n```", prompt, re.DOTALL)
            code = match.group(1) if match else "x = 1\n"
            return json.dumps({
                "repaired_code": code,
                "repair_category": "syntax",
                "root_cause": "No change made",
                "target_line": 1,
                "confidence": 0.5,
            })

        # Default 'normal' mode: produce realistic repairs for common patterns
        return self._generate_heuristic_repair(prompt)

    def _generate_heuristic_repair(self, prompt: str) -> str:
        """Examines the prompt to apply appropriate repairs for common errors."""
        # Extract raw code
        code_match = re.search(r"Raw code without line numbers:\s*```(?:\w+)?\n(.*?)\n```", prompt, re.DOTALL)
        raw_code = code_match.group(1) if code_match else ""
        lang_match = re.search(r"^Language:\s*(\w+)", prompt, re.MULTILINE)
        language = lang_match.group(1).lower() if lang_match else "python"

        repaired_code = raw_code
        category = "syntax"
        root_cause = "Repaired syntax mistake"
        target_line = 1
        confidence = 0.85

        # Heuristic 1: Extra argument mutation (e.g. ', 99999')
        if ", 99999" in raw_code:
            repaired_code = raw_code.replace(", 99999", "")
            category = "function_call_argument"
            root_cause = "Removed extraneous argument 99999"

        # Heuristic 2: Identifier misspelling mutation (e.g. '_undeclared_id')
        elif "_undeclared_id" in raw_code:
            repaired_code = raw_code.replace("_undeclared_id", "")
            category = "declaration_identifier"
            root_cause = "Restored undeclared identifier to original symbol"

        # Heuristic 3: Chained assignment mutation (e.g. '= 100 =')
        elif re.search(r"=\s*\d+\s*=", raw_code):
            repaired_code = re.sub(r"=\s*\d+\s*=", "=", raw_code)
            category = "expression_operator"
            root_cause = "Removed invalid chained assignment"

        # Heuristic 4: Invalid comparison mutation (e.g. '= <' or '= >')
        elif "= <" in raw_code or "= >" in raw_code:
            repaired_code = raw_code.replace("= <", "<").replace("= >", ">")
            category = "expression_operator"
            root_cause = "Fixed malformed comparison operator"

        # Heuristic 5: Python missing colon: 'def f(x)' or 'if x'
        elif language == "python" and re.search(r"(def \w+\([^)]*\)|if [^:\n]+|while [^:\n]+|for [^:\n]+)$", raw_code, re.MULTILINE):
            lines = raw_code.splitlines()
            for idx, line in enumerate(lines):
                if re.match(r"\s*(def|if|while|for|class|elif)\b.*[^:]$", line):
                    lines[idx] = line + ":"
                    target_line = idx + 1
                    root_cause = "Added missing colon at end of statement"
                    break
            repaired_code = "\n".join(lines) + ("\n" if raw_code.endswith("\n") else "")

        # Heuristic 6: Missing semicolon in C / C++
        elif language in {"c", "cpp", "c++"} and ("expected ';'" in prompt or "missing semicolon" in prompt.lower()):
            lines = raw_code.splitlines()
            for idx, line in enumerate(lines):
                s = line.strip()
                if (s and not s.endswith((";", "{", "}")) and not s.startswith("#")
                        and not re.match(r"(?:if|while|for|switch|else|do)\b", s)):
                    lines[idx] = line + ";"
                    target_line = idx + 1
                    root_cause = "Added missing semicolon terminator"
                    break
            repaired_code = "\n".join(lines) + ("\n" if raw_code.endswith("\n") else "")

        # Heuristic 7: Missing header in C / C++ (e.g. printf without stdio.h)
        elif (language in {"c", "cpp", "c++"} and "#include <stdio.h>" not in raw_code
              and re.search(r"implicit declaration of function 'printf'", prompt)
              and re.search(r"\bprintf\s*\(", raw_code)):
            repaired_code = "#include <stdio.h>\n" + raw_code
            target_line = 1
            category = "import"
            root_cause = "Included missing stdio.h header for printf"

        # Heuristic 8: Indentation error in Python
        elif language == "python" and "indent" in prompt.lower():
            lines = raw_code.splitlines()
            for idx, line in enumerate(lines):
                if line.strip() and not line.startswith(" ") and idx > 0 and lines[idx - 1].endswith(":"):
                    lines[idx] = "    " + line
                    target_line = idx + 1
                    category = "indentation"
                    root_cause = "Indented block under header statement"
                    break
            repaired_code = "\n".join(lines) + ("\n" if raw_code.endswith("\n") else "")

        # Heuristic 9: Undefined name / typo in Python
        elif language == "python" and ("undefined name 'totl'" in prompt or "totl" in raw_code):
            repaired_code = raw_code.replace("totl", "total")
            category = "declaration_identifier"
            root_cause = "Renamed misspelled identifier 'totl' to 'total'"

        # Fallback to P2 rule_repair if available
        else:
            try:
                from src.analysis_engine import detect, build_context, rule_repair
                det = detect(raw_code, language)
                if det.detected and det.root:
                    ctx = build_context(raw_code, det.root, language, det.diagnostics)
                    res = rule_repair(ctx)
                    if res.chosen and res.chosen.code != raw_code:
                        repaired_code = res.chosen.code
                        category = det.root.category
                        root_cause = res.chosen.description
                        target_line = res.chosen.line
                        confidence = res.chosen.confidence
            except Exception:
                pass

        # An unchanged response is filtered by candidate generation. Fabricating a
        # comment or punctuation edit here can only obscure the real diagnostic.

        return json.dumps({
            "repaired_code": repaired_code,
            "repair_category": category,
            "root_cause": root_cause,
            "target_line": target_line,
            "confidence": confidence,
        })


class HostedLLMProvider(ModelProvider):
    """Production provider connecting to hosted OpenAI/Gemini or compatible endpoints.

    All configurations and secrets are retrieved from environment variables.
    """

    def __init__(
        self,
        provider: Optional[str] = None,
        model_name: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout_seconds: float = 30.0,
    ):
        self.provider = (provider or os.environ.get("MODEL_PROVIDER", "openai")).lower()
        self.model_name = model_name or os.environ.get("MODEL_NAME") or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY") or os.environ.get("GEMINI_API_KEY")
        self.base_url = base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.timeout_seconds = timeout_seconds

    def is_available(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    def get_model_name(self) -> str:
        return f"{self.provider}:{self.model_name}"

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        **kwargs,
    ) -> str:
        if not self.is_available():
            raise ProviderUnavailableError(
                f"Hosted provider '{self.provider}' is unavailable. Set OPENAI_API_KEY or GEMINI_API_KEY."
            )

        import requests

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"} if "gpt" in self.model_name else None,
        }
        # Clean None values
        payload = {k: v for k, v in payload.items() if v is not None}

        endpoint = f"{self.base_url.rstrip('/')}/chat/completions"

        try:
            resp = requests.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=self.timeout_seconds,
            )
            if resp.status_code != 200:
                # Sanitize error to avoid leaking keys
                clean_err = resp.text.replace(self.api_key, "[REDACTED_API_KEY]")
                raise ProviderUnavailableError(f"HTTP {resp.status_code} from {self.provider}: {clean_err}")

            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except requests.exceptions.RequestException as e:
            err_msg = str(e).replace(self.api_key or "", "[REDACTED_API_KEY]")
            raise ProviderUnavailableError(f"Network error calling {self.provider}: {err_msg}")


# ---------------------------------------------------------------- Robust JSON Parser

def parse_model_output(raw_output: str) -> StructuredModelOutput:
    """Robustly extracts and validates JSON from raw model text.

    Handles:
    - Markdown code fences (```json ... ``` or ``` ... ```)
    - Extraneous prose before or after JSON
    - Empty or malformed payloads
    """
    if not isinstance(raw_output, str) or not raw_output.strip():
        raise ModelOutputParseError("Model output is empty or not a string")

    text = raw_output.strip()

    # Strip markdown code fences if wrapping the entire output
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if fence_match:
        text = fence_match.group(1).strip()

    # If text is not pure JSON, find the outermost '{' and '}'
    if not (text.startswith("{") and text.endswith("}")):
        start_idx = text.find("{")
        end_idx = text.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            text = text[start_idx : end_idx + 1]
        else:
            raise ModelOutputParseError(f"No JSON object found in model output:\n{raw_output[:200]}")

    try:
        data = json.loads(text)
    except json.JSONDecodeError as err:
        raise ModelOutputParseError(f"Failed to decode JSON from model response: {err}") from err

    if not isinstance(data, dict):
        raise ModelOutputParseError(f"Model JSON output must be a dict, got {type(data).__name__}")

    try:
        return StructuredModelOutput.model_validate(data)
    except Exception as err:
        raise ModelOutputParseError(f"Model output schema validation failed: {err}") from err


# ---------------------------------------------------------------- Repair Model Coordinator

class RepairModel:
    """Coordinates prompt construction, provider execution, and output parsing."""

    def __init__(self, provider: Optional[ModelProvider] = None):
        self.provider = provider or MockModelProvider()

    def generate_repair(
        self,
        ctx: ErrorContext,
        examples: Optional[List[FewShotExample]] = None,
        feedback: Optional[RepairFeedback] = None,
        previous_candidates: Optional[List[MLRepairCandidate]] = None,
        temperature: float = 0.0,
    ) -> StructuredModelOutput:
        """Run zero-shot, few-shot, or feedback repair on ErrorContext."""
        if not isinstance(ctx.code, str) or not ctx.code.strip():
            raise ValueError("ctx.code must be a non-empty string")
        if ctx.root is None:
            raise ValueError("ctx.root diagnostic cannot be None")

        # Snapshot original code to guarantee immutability
        original_code_snapshot = str(ctx.code)

        # Select prompt strategy
        if feedback is not None:
            sys_prompt, user_prompt = build_feedback_prompt(ctx, feedback, previous_candidates or [])
        elif examples:
            sys_prompt, user_prompt = build_few_shot_prompt(ctx, examples)
        else:
            sys_prompt, user_prompt = build_zero_shot_prompt(ctx)

        # Generate response
        raw_output = self.provider.generate(
            prompt=user_prompt,
            system_prompt=sys_prompt,
            temperature=temperature,
        )

        # Verify ctx was not mutated
        assert ctx.code == original_code_snapshot, "ErrorContext code was mutated during generation!"

        # Parse and validate response
        structured = parse_model_output(raw_output)
        return structured
