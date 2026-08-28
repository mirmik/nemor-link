import json

from nemor_link.state import StateStore


def test_legacy_global_preferences_are_not_assigned_to_an_application(tmp_path):
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
        "applications": {},
        "servers": {
            "server": {
                "fingerprint": "fingerprint",
                "endpoints": ["https://server:8090"],
            }
        },
    }
