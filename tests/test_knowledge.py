import numpy as np
import pytest

from nimbus.errors import NimbusError
from nimbus.knowledge import Knowledge, cosine_scores, read_source


def test_duplicate_source_ids_cannot_authorize_a_policy(tmp_path):
    metadata = """---
source_id: same_policy
document_type: verification_policy
policy_version: 1
approval_status: approved
machine_types: [fixture]
required_checks:
  - check_id: fixture_check
---
Fixture verification policy.
"""
    (tmp_path / "first.md").write_text(metadata, encoding="utf-8")
    (tmp_path / "second.md").write_text(metadata, encoding="utf-8")
    with pytest.raises(NimbusError) as captured:
        Knowledge(tmp_path).policy("same_policy")
    assert captured.value.code == "duplicate_knowledge_id"


def test_invalid_yaml_is_an_actionable_error(tmp_path):
    path = tmp_path / "bad.md"
    path.write_text("---\nsource_id: [unclosed\n---\nBody", encoding="utf-8")
    with pytest.raises(NimbusError) as captured:
        read_source(path)
    assert captured.value.code == "invalid_knowledge_metadata"


def test_revoked_knowledge_is_excluded_from_retrieval(tmp_path):
    (tmp_path / "revoked.md").write_text(
        "---\nsource_id: revoked\napproval_status: revoked\n---\nVibration repair.",
        encoding="utf-8",
    )
    assert Knowledge(tmp_path).search("vibration") == []


def test_cosine_scoring_handles_zero_vectors_and_rejects_mixed_dimensions():
    assert np.allclose(cosine_scores([[1, 0], [0, 0], [0, 1]], [1, 0]), [1, 0, 0])
    with pytest.raises(NimbusError) as captured:
        cosine_scores([[1, 0]], [1, 0, 1])
    assert captured.value.code == "embedding_dimensions_mismatch"
