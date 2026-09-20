from __future__ import annotations

import hashlib
import json
import unittest

from src.ai_autocut.artifact_reference import (
    ArtifactReference,
    ArtifactReferenceError,
    artifact_reference,
    canonical_text_sha256,
    parse_artifact_reference,
    render_artifact_reference,
    validate_logical_ref,
    validate_reference_binding,
    validate_sha256,
)


# Probe paths are assembled from fragments on purpose: this repository is scanned
# by the path-hygiene test, which would otherwise flag this module's own probe.
def absolute(*parts: str) -> str:
    """Build an absolute POSIX path without writing a literal prefix."""

    return "/" + "/".join(parts)


DIGEST = hashlib.sha256(b"payload").hexdigest()


class LogicalRefTests(unittest.TestCase):
    def test_valid_logical_refs(self) -> None:
        for value in (
            "analysis/candidate_evidence.json",
            "planning/hook_decision.json",
            "brief.json",
            "a/b/c/d.json",
        ):
            with self.subTest(value=value):
                self.assertEqual(validate_logical_ref(value), value)

    def test_machine_bound_and_ambiguous_refs_fail_closed(self) -> None:
        for value in (
            absolute("Users", "someone", "job", "evidence.json"),
            "../../etc/passwd.json",
            "~/evidence.json",
            "C:\\job\\evidence.json",
            "analysis\\candidate_evidence.json",
            "analysis/candidate evidence.json",
            "analysis/candidate_evidence.yaml",
            "",
            None,
            42,
        ):
            with self.subTest(value=value):
                with self.assertRaises(ArtifactReferenceError):
                    validate_logical_ref(value)

    def test_path_like_ref_is_not_echoed_in_error(self) -> None:
        private = absolute("Users", "someone", "secret", "job.json")
        with self.assertRaises(ArtifactReferenceError) as caught:
            validate_logical_ref(private)
        self.assertNotIn(private, str(caught.exception))

    def test_sha256_validation(self) -> None:
        self.assertEqual(validate_sha256(DIGEST), DIGEST)
        for value in (DIGEST.upper(), DIGEST[:-1], "z" * 64, "", None, 7):
            with self.subTest(value=value):
                with self.assertRaises(ArtifactReferenceError):
                    validate_sha256(value)


class ReferenceBindingTests(unittest.TestCase):
    def test_reference_matches_exact_bytes(self) -> None:
        reference = artifact_reference("analysis/evidence.json", "{\n}\n")
        self.assertTrue(reference.matches_text("{\n}\n"))
        self.assertFalse(reference.matches_text("{}\n"))
        validate_reference_binding(reference, "{\n}\n")

    def test_stale_bytes_and_wrong_ref_fail_closed(self) -> None:
        reference = artifact_reference("analysis/evidence.json", "{}\n")
        with self.assertRaisesRegex(ArtifactReferenceError, "does not match"):
            validate_reference_binding(reference, '{"changed": true}\n')
        with self.assertRaises(ArtifactReferenceError):
            parse_artifact_reference(
                {"ref": "analysis/other.json", "sha256": DIGEST},
                expected_ref="analysis/evidence.json",
            )

    def test_parse_is_exact_key_and_round_trips(self) -> None:
        reference = artifact_reference("analysis/evidence.json", "{}\n")
        parsed = parse_artifact_reference(
            json.loads(render_artifact_reference(reference))
        )
        self.assertEqual(parsed, reference)
        self.assertEqual(
            canonical_text_sha256("{}\n"),
            hashlib.sha256(b"{}\n").hexdigest(),
        )
        for payload in (
            {"ref": "analysis/evidence.json"},
            {"ref": "analysis/evidence.json", "sha256": DIGEST, "path": "/tmp/x"},
            {"ref": "analysis/evidence.json", "sha256": DIGEST, "extra": 1},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(ArtifactReferenceError):
                    parse_artifact_reference(payload)

    def test_reference_type_is_enforced(self) -> None:
        with self.assertRaises(ArtifactReferenceError):
            render_artifact_reference("analysis/evidence.json")  # type: ignore[arg-type]
        with self.assertRaises(ArtifactReferenceError):
            validate_reference_binding("analysis/evidence.json", "{}\n")  # type: ignore[arg-type]
        with self.assertRaises(ArtifactReferenceError):
            ArtifactReference("analysis/evidence.json", "not-a-digest")


if __name__ == "__main__":
    unittest.main()
