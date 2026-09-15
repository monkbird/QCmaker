import json

from backend.app.services import admin_metrics as metrics


def test_log_cursor_reads_only_appended_lines(tmp_path, monkeypatch):
    monkeypatch.setattr(metrics, 'LOG_DIR', tmp_path)
    path = tmp_path / 'app.log'
    path.write_text('2026-09-13 10:00:00 INFO app first\n', encoding='utf-8')
    initial = metrics.read_logs()
    with path.open('a', encoding='utf-8') as stream:
        stream.write('2026-09-13 10:00:01 INFO app second\n')
    appended = metrics.read_logs(cursor=initial['cursor'])
    text = json.dumps(appended['lines'])
    assert 'second' in text
    assert 'first' not in text
    assert metrics.read_logs(cursor=appended['cursor'])['lines'] == []


def test_log_rotation_starts_new_file(tmp_path, monkeypatch):
    monkeypatch.setattr(metrics, 'LOG_DIR', tmp_path)
    path = tmp_path / 'app.log'
    path.write_text('2026-09-13 10:00:00 INFO app old\n', encoding='utf-8')
    initial = metrics.read_logs()
    path.rename(tmp_path / 'app.log.1')
    path.write_text('2026-09-13 10:00:01 INFO app rotated\n', encoding='utf-8')
    assert 'rotated' in json.dumps(metrics.read_logs(cursor=initial['cursor'])['lines'])


def test_known_configured_secrets_are_redacted_in_free_text(isolated_settings, monkeypatch):
    monkeypatch.setattr(isolated_settings, 'OPENAI_API_KEY', 'arbitrary-private-credential')
    output = metrics.redact_text('provider error echoed arbitrary-private-credential in response')
    assert 'arbitrary-private-credential' not in output
