"""Transcript cleanup via the LM Studio local server (OpenAI-compatible API).

Any failure — server down, timeout, bad response — falls back to the raw transcript,
so dictation keeps working even without LM Studio.
"""

import json
import logging
import subprocess
import threading

import requests

log = logging.getLogger(__name__)

INSTRUCTIONS = """You clean up dictated speech transcripts. Rules:
- Add proper punctuation, capitalization and, for long dictations, paragraph breaks.
- Remove filler words (um, uh, you know, like) and false starts, keeping the speaker's intended final phrasing.
- Never add information, never answer questions contained in the text, never change the meaning.
- Output ONLY the cleaned text. No commentary, no quotes around it.{dictionary}

Transcript:
{raw}"""


class Formatter:
    def __init__(self, lmstudio_cfg: dict, dictionary: dict):
        self._cfg = lmstudio_cfg
        self._dictionary = dictionary
        self._client = None
        self._lock = threading.Lock()

    def _get_client(self):
        with self._lock:
            if self._client is None:
                from openai import OpenAI

                self._client = OpenAI(
                    base_url=self._cfg["base_url"],
                    api_key="lm-studio",
                    timeout=self._cfg["timeout_seconds"],
                    max_retries=0,
                )
            return self._client

    def _prompt(self, raw: str) -> str:
        dictionary = ""
        if self._dictionary:
            rules = "; ".join(f'"{heard}" means "{meant}"' for heard, meant in self._dictionary.items())
            dictionary = f"\n- Apply these vocabulary corrections: {rules}."
        return INSTRUCTIONS.format(dictionary=dictionary, raw=raw)

    def clean(self, raw: str) -> str:
        if not self._cfg["enabled"] or not raw.strip():
            return raw
        try:
            response = self._get_client().chat.completions.create(
                model=self._cfg["model"],
                messages=[{"role": "user", "content": self._prompt(raw)}],
                temperature=0,
            )
            text = (response.choices[0].message.content or "").strip()
            # models occasionally wrap the result in quotes despite instructions
            if len(text) > 1 and text[0] == text[-1] and text[0] in "\"'“":
                text = text[1:-1].strip()
            if not text:
                log.warning("LM Studio returned empty text; using raw transcript")
                return raw
            return text
        except Exception as exc:
            log.warning("LM Studio cleanup failed (%s); using raw transcript", exc)
            return raw

    # --- server management -------------------------------------------------

    def server_reachable(self) -> bool:
        try:
            requests.get(self._cfg["base_url"].rstrip("/") + "/models", timeout=3)
            return True
        except requests.RequestException:
            return False

    def _model_loaded(self) -> bool:
        try:
            result = subprocess.run(
                ["lms", "ps", "--json"],
                capture_output=True, text=True, timeout=30, shell=True, check=False,
            )
            loaded = json.loads(result.stdout or "[]")
            return any(
                self._cfg["model"] in (m.get("identifier"), m.get("modelKey"))
                for m in loaded
            )
        except Exception as exc:
            log.debug("Could not query loaded models (%s)", exc)
            return False  # fall through to `lms load`, which is a no-op-ish if loaded

    def ensure_server(self):
        """Start the LM Studio server and load the model if needed, then warm it up."""
        if not self._cfg["enabled"]:
            return
        if not self.server_reachable():
            if not self._cfg.get("auto_start_server"):
                log.warning("LM Studio server unreachable; cleanup will fall back to raw transcripts")
                return
            log.info("LM Studio server not running; starting it via `lms server start`...")
            try:
                subprocess.run(
                    ["lms", "server", "start"],
                    capture_output=True, timeout=60, shell=True, check=False,
                )
            except Exception as exc:
                log.warning("Could not start LM Studio server (%s)", exc)
                return
            if not self.server_reachable():
                log.warning("LM Studio server still unreachable; cleanup disabled for now")
                return
        if not self._model_loaded():
            log.info("Loading %r into LM Studio (this can take a minute)...", self._cfg["model"])
            try:
                subprocess.run(
                    ["lms", "load", self._cfg["model"], "-y",
                     "--gpu", str(self._cfg.get("gpu_offload", "off"))],
                    capture_output=True, timeout=600, shell=True, check=False,
                )
            except Exception as exc:
                log.warning("Could not load model via lms (%s)", exc)
        try:
            log.info("Warming up LM Studio model %r...", self._cfg["model"])
            self._get_client().with_options(timeout=300).chat.completions.create(
                model=self._cfg["model"],
                messages=[{"role": "user", "content": "Reply with the single word: ok"}],
                max_tokens=4,
                temperature=0,
            )
            log.info("LM Studio model ready")
        except Exception as exc:
            log.warning("LM Studio warm-up failed (%s); will fall back to raw transcripts", exc)
