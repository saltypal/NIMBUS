import json

from nimbus.cli import execute, parser
from nimbus.config import ROOT


def test_capture_process_inspect_confirm_are_separate_commands(service, tmp_path, monkeypatch):
    # Share this explicitly isolated store across commands; no real Mongo/model
    # is used in this CLI contract check.
    monkeypatch.setattr("nimbus.cli.create_store", lambda settings: service.store)
    metadata = ROOT / "examples/report-capture.json"
    source = ROOT / "examples/report.txt"
    captured = execute(parser().parse_args(["capture", str(metadata), "--input", str(source)]))
    assert captured["processing_status"] == "saved"
    assert service.store.find("tickets") == []
    ready = execute(parser().parse_args(["process", "--submission-id", captured["_id"]]))
    assert ready["processing_status"] == "ready_for_review"
    inspected = execute(parser().parse_args(["inspect", "submissions", captured["_id"]]))
    assert inspected["source"]["original_text"] == source.read_text(encoding="utf-8")
    confirmation = {
        "operation_id": "fixture-cli-confirm",
        "draft_revision": ready["draft_revision"],
        "text_revision": ready["selected_text_revision"],
        "expected_processing_version": ready["processing_version"],
        "expected_ticket_version": None,
        "reviewed_by": ready["actor"],
        "fields": ready["draft"]["fields"],
    }
    reviewed = tmp_path / "reviewed.json"
    # Windows PowerShell's Set-Content -Encoding utf8 can write a BOM.
    reviewed.write_text(json.dumps(confirmation), encoding="utf-8-sig")
    accepted = execute(parser().parse_args(["confirm", captured["_id"], str(reviewed)]))
    assert accepted["status"] == "open"
    assert len(service.store.find("tickets")) == 1
