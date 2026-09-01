import json

from inference_link.state import StateStore


def test_legacy_global_preferences_become_the_default(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "active_server": "server",
                "servers": {
                    "server": {
                        "fingerprint": "fingerprint",
                        "endpoints": ["https://server:8090"],
                        "token": "secret",
                        "selections": {"llm": "model"},
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    state = StateStore(path).load()

    assert state == {
        "version": 2,
        "default": {
            "server": "server",
            "token": "secret",
            "model": "model",
        },
        "applications": {},
        "servers": {
            "server": {
                "fingerprint": "fingerprint",
                "endpoints": ["https://server:8090"],
            }
        },
    }


def test_old_product_state_path_is_used_until_new_state_is_written(tmp_path):
    old_path = tmp_path / "nemor-link" / "state.json"
    new_path = tmp_path / "inference-link" / "state.json"
    old_path.parent.mkdir()
    old_path.write_text(
        json.dumps(
            {
                "version": 2,
                "default": {"server": "server"},
                "applications": {},
                "servers": {
                    "server": {
                        "fingerprint": "fingerprint",
                        "endpoints": ["https://server:8090"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    store = StateStore(new_path, legacy_path=old_path)

    state = store.load()
    state["default"]["model"] = "model"
    store.save(state)

    assert json.loads(new_path.read_text(encoding="utf-8"))["default"] == {
        "server": "server",
        "model": "model",
    }
    assert old_path.is_file()
