"""Reproducible in-process benchmark for the response cache."""

import importlib.util
import os
import pathlib
import tempfile
import time
from importlib.machinery import SourceFileLoader
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "config/includes.chroot/usr/local/bin/neuroslib.py"


class Response:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return b'{"response":"benchmark response"}'


def main():
    loader = SourceFileLoader("neuroslib_benchmark", str(LIBRARY))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    with tempfile.TemporaryDirectory() as tmp:
        module.RESPONSE_CACHE_PATH = os.path.join(tmp, "responses.json")
        config = {"model": "mistral", "host": "localhost", "port": "11434"}
        with patch.object(module, "load_config", return_value=config), \
             patch("urllib.request.urlopen", return_value=Response()) as request:
            start = time.perf_counter()
            module.query_llm("benchmark prompt")
            cold = time.perf_counter() - start
            start = time.perf_counter()
            module.query_llm("benchmark prompt")
            warm = time.perf_counter() - start
        print(f"cold_seconds={cold:.9f}")
        print(f"cached_seconds={warm:.9f}")
        print(f"network_calls={request.call_count}")
        print(f"speedup={cold / warm:.2f}x")


if __name__ == "__main__":
    main()
