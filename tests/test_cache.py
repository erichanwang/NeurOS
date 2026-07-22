"""Tests for the shared NeurOS response cache."""

import importlib.util
import json
import os
import pathlib
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from unittest.mock import patch


LIBRARY_PATH = pathlib.Path(__file__).resolve().parents[1] / "config/includes.chroot/usr/local/bin/neuroslib.py"


def load_library():
    loader = SourceFileLoader("neuroslib_cache_test", str(LIBRARY_PATH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload


class ResponseCacheTests(unittest.TestCase):
    def test_same_prompt_and_model_uses_cached_response(self):
        module = load_library()
        with tempfile.TemporaryDirectory() as tmp:
            module.RESPONSE_CACHE_PATH = os.path.join(tmp, "responses.json")
            with patch.object(module, "load_config", return_value={"model": "mistral", "host": "localhost", "port": "11434"}), \
                 patch("urllib.request.urlopen", return_value=FakeResponse({"response": "cached"})) as request:
                self.assertEqual(module.query_llm("same"), "cached")
                self.assertEqual(module.query_llm("same"), "cached")
            self.assertEqual(request.call_count, 1)

    def test_model_is_part_of_cache_key(self):
        module = load_library()
        with tempfile.TemporaryDirectory() as tmp:
            module.RESPONSE_CACHE_PATH = os.path.join(tmp, "responses.json")
            configs = iter([
                {"model": "mistral", "host": "localhost", "port": "11434"},
                {"model": "llama3", "host": "localhost", "port": "11434"},
            ])
            with patch.object(module, "load_config", side_effect=lambda: next(configs)), \
                 patch("urllib.request.urlopen", side_effect=[FakeResponse({"response": "one"}), FakeResponse({"response": "two"})]) as request:
                self.assertEqual(module.query_llm("same"), "one")
                self.assertEqual(module.query_llm("same"), "two")
            self.assertEqual(request.call_count, 2)

    def test_cache_write_is_json_and_failure_is_not_cached(self):
        module = load_library()
        with tempfile.TemporaryDirectory() as tmp:
            module.RESPONSE_CACHE_PATH = os.path.join(tmp, "responses.json")
            with patch.object(module, "load_config", return_value={"model": "mistral", "host": "localhost", "port": "11434"}), \
                 patch("urllib.request.urlopen", return_value=FakeResponse({"response": ""})) as request:
                self.assertEqual(module.query_llm("empty"), "")
                self.assertEqual(module.query_llm("empty"), "")
            self.assertEqual(request.call_count, 2)
            self.assertFalse(os.path.exists(module.RESPONSE_CACHE_PATH))


if __name__ == "__main__":
    unittest.main()
