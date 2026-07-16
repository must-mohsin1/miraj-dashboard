from pathlib import Path


def test_realtime_discord_alert_uses_a_valid_embed_description():
    source = Path("backend/realtime/worker.py").read_text()
    assert '{"description": text}' in source
