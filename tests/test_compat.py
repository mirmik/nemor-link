import importlib
import json
import sys
import warnings
from unittest.mock import patch

import inference_link
from inference_link.config import load


def test_legacy_import_aliases_canonical_package_and_submodules():
    sys.modules.pop("nemor_link", None)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        legacy = importlib.import_module("nemor_link")

    legacy_connection = importlib.import_module("nemor_link.connection")
    canonical_connection = importlib.import_module("inference_link.connection")

    assert legacy.llm is inference_link.llm
    assert legacy_connection is canonical_connection
    assert any("inference_link" in str(item.message) for item in caught)


def test_legacy_profile_path_is_used_as_fallback(tmp_path):
    new_path = tmp_path / "inference-link" / "profiles.json"
    old_path = tmp_path / "llm.json"
    old_path.write_text(
        json.dumps({"profiles": {}, "defaults": {}, "hosts": {}}),
        encoding="utf-8",
    )

    with patch("inference_link.config.CONFIG_PATH", str(new_path)), patch(
        "inference_link.config.LEGACY_CONFIG_PATH", str(old_path)
    ):
        config = load()

    assert config["_path"] == str(old_path)
