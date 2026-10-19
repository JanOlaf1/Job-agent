from pathlib import Path
import subprocess
import sys
import pytest
from src.main import run
from src.tracker import load_tracker

FIXTURE = Path(__file__).parent / "fixtures" / "run.json"


def test_dry_run_and_second_persisted_run(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    preview = tmp_path / "preview"
    result = run(data, preview, fixture=FIXTURE)
    assert result["strong_count"] == 3
    assert len(result["new_studies"]) == 2
    assert result["status"] == "DEGRADED"
    assert not (data / "job_tracker.csv").exists()
    assert (preview / "email_preview.txt").exists()
    run(data, preview, fixture=FIXTURE, commit=True)
    assert len(load_tracker(data / "job_tracker.csv")) == 4
    assert len(load_tracker(data / "study_tracker.csv", "study_id")) == 2
    result = run(data, preview, fixture=FIXTURE, commit=True)
    # Saving discoveries alone must not pretend they were emailed.
    assert result["new_count"] == 0
    assert len(result["new_jobs"]) == 3
    assert len(result["new_studies"]) == 2


def test_smtp_failure_preserves_history_and_pending_digest(tmp_path, monkeypatch):
    for name in ("SMTP_USER", "SMTP_PASSWORD", "EMAIL_TO"):
        monkeypatch.setenv(name, "test")
    def failed(message):
        raise OSError("SMTP unavailable")
    monkeypatch.setattr("src.main.send_email", failed)
    with pytest.raises(OSError):
        run(tmp_path, tmp_path / "reports", fixture=FIXTURE, commit=True, mail=True)
    assert (tmp_path / "pending_email.json").exists()
    assert len(load_tracker(tmp_path / "job_tracker.csv")) == 4
    sent = []
    monkeypatch.setattr("src.main.send_email", sent.append)
    result = run(tmp_path, tmp_path / "reports", fixture=FIXTURE, commit=True, mail=True)
    assert "Solutions Consultant" in sent[0].get_body(preferencelist=("plain",)).get_content()
    assert len(sent) == 1
    assert all(r.get("sent_at") for r in load_tracker(tmp_path / "job_tracker.csv").values() if r["notification_status"] == "sent")
    assert not (tmp_path / "pending_email.json").exists()
    again = run(tmp_path, tmp_path / "reports", fixture=FIXTURE, commit=True, mail=True)
    assert again["new_jobs"] == []
    assert again["new_studies"] == []
    assert len(sent) == 1


def test_launcher_works_outside_project_directory(tmp_path):
    root = FIXTURE.parents[2]
    completed = subprocess.run([sys.executable, str(root / "main.py"), "--fixture", str(FIXTURE),
                                "--output-dir", str(tmp_path / "reports")], cwd=tmp_path,
                               capture_output=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    assert (tmp_path / "reports" / "jobs.md").exists()


def test_direct_script_explains_module_command_without_traceback():
    completed = subprocess.run([sys.executable, str(FIXTURE.parents[2] / "src" / "main.py")],
                               capture_output=True, timeout=30)
    assert completed.returncode != 0
    assert b"python -m src.main" in completed.stderr
    assert b"Traceback" not in completed.stderr


def test_missing_dependencies_have_installation_instructions():
    completed = subprocess.run([sys.executable, "-S", "-m", "src.main"], cwd=FIXTURE.parents[2],
                               capture_output=True, timeout=30)
    assert completed.returncode != 0
    assert b"pip install -r requirements.txt" in completed.stderr
    assert b"Traceback" not in completed.stderr


def test_missing_smtp_settings_fail_before_history_writes(tmp_path, monkeypatch):
    for name in ("SMTP_USER", "SMTP_PASSWORD", "EMAIL_TO"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError, match="SMTP_USER.*SMTP_PASSWORD.*EMAIL_TO"):
        run(tmp_path, tmp_path / "reports", fixture=FIXTURE, commit=True, mail=True)
    assert not list(tmp_path.iterdir())


def test_unexpected_error_saves_complete_traceback(tmp_path, monkeypatch):
    import src.main as app
    def fail(*args, **kwargs):
        raise ValueError("Fixture pipeline failure")
    monkeypatch.setattr(app, "run", fail)
    monkeypatch.setattr(app, "load_dotenv", lambda path: None)
    monkeypatch.setattr(sys, "argv", ["job-agent", "--output-dir", str(tmp_path)])
    assert app.main() == 1
    log = (tmp_path / "error.log").read_text(encoding="utf-8")
    assert "Traceback (most recent call last)" in log
    assert "ValueError: Fixture pipeline failure" in log
    assert "test_main.py" in log


def test_keyboard_interrupt_exits_cleanly(tmp_path, monkeypatch, capsys):
    import src.main as app
    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt()
    monkeypatch.setattr(app, "run", interrupt)
    monkeypatch.setattr(app, "load_dotenv", lambda path: None)
    monkeypatch.setattr(sys, "argv", ["job-agent", "--output-dir", str(tmp_path)])
    assert app.main() == 130
    assert "Ctrl+C" in capsys.readouterr().out
    assert not (tmp_path / "error.log").exists()
