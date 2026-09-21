"""Frame evidence and the Phase 2.5 analyzer boundary. Deterministic and offline.

The live validation run is opt-in (`scripts/phase25_live_validation.py`) and is NOT
part of this suite. Everything here runs with no provider and no network.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from src.ai_autocut import authoring, producer_registry
from src.ai_autocut.candidate_analysis import (
    ANALYZER_PROMPT_CONTRACT_VERSION,
    ANALYZER_PROMPT_V2,
    ANALYSIS_QUESTION,
    PROMPT_CONTRACT_VERSION,
    PROMPT_CONTRACTS,
    CandidateAnalysisError,
    CandidateAnalysisRequest,
    ClaimEnvelope,
    ClaimFact,
    build_candidate_evidence,
    parse_analysis_response,
    prompt_for,
    render_analysis_request,
    run_candidate_evidence_stage,
    targets_from_extraction,
)
from src.ai_autocut.candidate_evidence import (
    AnalysisRun,
    CandidateEvidenceEntry,
    ClaimSupport,
    ClaimSupportRecord,
    EvidenceStatus,
    EvidenceType,
    Observations,
    ProductFacts,
)
from src.ai_autocut.candidate_evidence_v2 import (
    ActionPresence,
    CandidateEvidenceEntryV2,
    CandidateEvidenceV2,
    ObservableState,
    ObservationsV2,
)
from src.ai_autocut.candidate_frame_evidence import (
    AuditVerdict,
    FrameAudit,
    ProvenanceFinding,
)
from src.ai_autocut.editing_intelligence import ActionEvidence
from src.ai_autocut.frame_boundary import SourceRange
from src.ai_autocut.candidate_extraction import (
    SegmentSpan,
    SourceMeasurement,
    SourceSegmentation,
    extract_candidates,
    proposals_from_segmentation,
)
from src.ai_autocut.candidate_frame_evidence import (
    DEFAULT_SAMPLE_COUNT,
    CheckStatus,
    CHECK_SCOPE,
    declared_check_status,
    FRAME_EVIDENCE_ARTIFACT,
    MAX_SAMPLE_COUNT,
    ChangeDirection,
    FrameAudit,
    FrameCheckKind,
    FrameEvidenceError,
    ProvenanceCheck,
    RegionOfInterest,
    audit_frame_provenance,
    build_contact_sheet,
    build_frame_evidence,
    parse_frame_evidence,
    render_frame_evidence,
    sample_frame_indices,
)
from src.ai_autocut.identity import (
    IdentityCatalog,
    MaterialIdentity,
    identify_material,
    material_id_from_sha256,
)

FIXTURES = Path(__file__).parent / "fixtures"
PHASE2_ENVELOPE = FIXTURES / "phase2_claim_envelope_v1.json"
PHASE2_CATALOG = FIXTURES / "phase2_identity_catalog_v1.json"
PHASE2_MEASUREMENTS = FIXTURES / "phase2_candidate_measurements_v1.json"
PHASE2_SEGMENTATIONS = FIXTURES / "phase2_candidate_segmentations_v1.json"
PHASE2_PROPOSALS = FIXTURES / "phase2_candidate_window_proposal_v1.json"
PHASE2_RESPONSE = FIXTURES / "phase2_candidate_analysis_response_v1.json"


def _has_ffmpeg() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _run(command: list[str], label: str) -> None:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(f"{label} failed: {result.stderr[-300:]}")


def build_two_tone_clip(path: Path) -> Path:
    """A real clip that is dark for one second and bright for the next."""

    _run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=black:size=96x96:rate=30:duration=1",
            "-f", "lavfi", "-i", "color=c=white:size=96x96:rate=30:duration=1",
            "-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", str(path),
        ],
        "building the two-tone clip",
    )
    return path


def _build_tone_clip(path: Path, first: str, second: str) -> Path:
    """A real clip that is one tone for a second, then another."""

    _run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"color=c={first}:size=96x96:rate=30:duration=1",
            "-f", "lavfi", "-i", f"color=c={second}:size=96x96:rate=30:duration=1",
            "-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", str(path),
        ],
        "building the tone clip",
    )
    return path


class SamplingTests(unittest.TestCase):
    def test_sampling_is_deterministic_and_includes_both_ends(self) -> None:
        first = sample_frame_indices(20, 88, 8)
        self.assertEqual(first, sample_frame_indices(20, 88, 8))
        self.assertEqual(first[0], 20)
        self.assertEqual(first[-1], 87)
        self.assertEqual(list(first), sorted(first))
        self.assertEqual(len(set(first)), len(first))
        self.assertEqual(first, (20, 30, 39, 49, 58, 68, 77, 87))

    def test_a_short_window_shows_every_frame(self) -> None:
        self.assertEqual(sample_frame_indices(30, 34, 8), (30, 31, 32, 33))

    def test_sampling_bounds_are_enforced(self) -> None:
        for args in ((30, 30, 8), (30, 20, 8), (0, 90, 1), (0, 90, MAX_SAMPLE_COUNT + 1)):
            with self.subTest(args=args):
                with self.assertRaises(FrameEvidenceError):
                    sample_frame_indices(*args)
        with self.assertRaises(FrameEvidenceError):
            sample_frame_indices(0, 90, True)  # bool is not an int here
        self.assertEqual(DEFAULT_SAMPLE_COUNT, 8)


class RegionTests(unittest.TestCase):
    def test_a_region_is_a_fraction_and_maps_to_pixels(self) -> None:
        region = RegionOfInterest(0.10, 0.30, 0.35, 0.50)
        rows, columns = region.pixels(200, 100)
        self.assertEqual((rows.start, rows.stop), (30, 80))
        self.assertEqual((columns.start, columns.stop), (20, 90))

    def test_an_invalid_region_is_refused(self) -> None:
        for args in (
            (0.9, 0.0, 0.2, 0.5),
            (0.0, 0.9, 0.5, 0.2),
            (0.0, 0.0, 0.0, 0.5),
            (-0.1, 0.0, 0.5, 0.5),
            (0.0, 0.0, 1.5, 0.5),
        ):
            with self.subTest(args=args):
                with self.assertRaises(FrameEvidenceError):
                    RegionOfInterest(*args)


class PromptContractTests(unittest.TestCase):
    def test_both_contracts_are_versioned_and_resolvable(self) -> None:
        self.assertEqual(PROMPT_CONTRACT_VERSION, "candidate_evidence_prompt.v1")
        self.assertEqual(ANALYZER_PROMPT_CONTRACT_VERSION, "candidate_evidence_prompt.v2")
        self.assertIn(PROMPT_CONTRACT_VERSION, PROMPT_CONTRACTS)
        self.assertEqual(prompt_for(PROMPT_CONTRACT_VERSION), ANALYSIS_QUESTION)
        self.assertEqual(prompt_for(ANALYZER_PROMPT_CONTRACT_VERSION), ANALYZER_PROMPT_V2)
        with self.assertRaises(CandidateAnalysisError):
            prompt_for("candidate_evidence_prompt.v99")

    def test_the_v2_contract_states_the_evidence_ladder(self) -> None:
        for register in ("OBSERVATION", "DIRECT", "CONTEXTUAL", "INFERRED", "UNSUPPORTED"):
            with self.subTest(register=register):
                self.assertIn(register, ANALYZER_PROMPT_V2)

    def test_the_v2_contract_prohibits_the_known_failure_modes(self) -> None:
        text = " ".join(ANALYZER_PROMPT_V2.lower().split())
        for prohibition in (
            "never introduce a product fact",
            "never upgrade inferred or contextual to direct",
            "never claim a result you cannot see",
            "never assume the product works from how it looks",
            "beauty or hero shot of the product is not efficacy evidence",
            "never invent, estimate, or interpolate source frame numbers",
            "never silently omit one",
        ):
            with self.subTest(prohibition=prohibition):
                self.assertIn(prohibition, text)

    def test_the_v2_contract_asks_for_the_contract_entry_shape(self) -> None:
        for key in (
            "candidate_id",
            "status",
            "observations",
            "action_evidence",
            "claims",
            "evidence_type",
            "confidence",
            "provenance",
            "role_affinities",
            "risks",
            "rationale",
        ):
            with self.subTest(key=key):
                self.assertIn(key, ANALYZER_PROMPT_V2)


class PrewrittenAgentTests(unittest.TestCase):
    def test_the_agent_asserts_presence_without_claiming_production(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        agent = authoring.PrewrittenAuthoringAgent()
        request = authoring.AuthoringRequest(
            artifact="analysis/candidate_analysis_response.json",
            stage="ANALYZE CANDIDATES",
            producer_id="analyzer",
            procedure="answer the request",
            output_contract="candidate_analysis_response.v1",
            required_inputs=(),
            job_root=tmp,
        )
        self.assertFalse(agent.author(request))
        target = tmp / request.artifact
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}\n", encoding="utf-8")
        self.assertTrue(agent.author(request))

    def test_the_artifact_filter_is_enforced(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        other = tmp / "analysis/other.json"
        other.parent.mkdir(parents=True, exist_ok=True)
        other.write_text("{}\n", encoding="utf-8")
        agent = authoring.PrewrittenAuthoringAgent(
            producer_registry.CANDIDATE_ANALYSIS_RESPONSE_ARTIFACT
        )
        request = authoring.AuthoringRequest(
            artifact="analysis/other.json",
            stage="ANALYZE CANDIDATES",
            producer_id="x",
            procedure="p",
            output_contract="c",
            required_inputs=(),
            job_root=tmp,
        )
        self.assertFalse(agent.author(request))


class PromptVersionWiringTests(unittest.TestCase):
    """The version a request is rendered under and the version a response declares
    must be the same object, or the answer is refused."""

    @classmethod
    def setUpClass(cls) -> None:
        from src.ai_autocut.candidate_analysis import (
            parse_claim_envelope,
            parse_measurements,
            parse_segmentations,
        )
        from src.ai_autocut.candidate_extraction import parse_window_proposals
        from src.ai_autocut.identity import parse_identity_catalog

        cls.envelope = parse_claim_envelope(json.loads(PHASE2_ENVELOPE.read_text()))
        cls.bundle = {}
        catalog = parse_identity_catalog(json.loads(PHASE2_CATALOG.read_text()))
        measurements = parse_measurements(json.loads(PHASE2_MEASUREMENTS.read_text()))
        segmentations = parse_segmentations(json.loads(PHASE2_SEGMENTATIONS.read_text()))
        proposals = parse_window_proposals(json.loads(PHASE2_PROPOSALS.read_text()))
        cls.extraction = extract_candidates(
            catalog=catalog,
            measurements=measurements,
            segmentations=segmentations,
            proposals=proposals,
        )
        cls.response_raw = json.loads(PHASE2_RESPONSE.read_text())

    def test_v1_stays_the_default_and_the_phase_2_fixture_still_answers_it(self) -> None:
        request = CandidateAnalysisRequest(
            run_id=self.response_raw["run_id"],
            candidate_pool_id=self.extraction.pool.pool_id,
            claim_envelope=self.envelope,
            targets=targets_from_extraction(self.extraction),
        )
        self.assertEqual(request.prompt_contract_version, PROMPT_CONTRACT_VERSION)
        self.assertEqual(request.question, ANALYSIS_QUESTION)
        response = parse_analysis_response(
            self.response_raw,
            request=request,
            request_text=render_analysis_request(request),
        )
        self.assertIsNone(response.response_failure)
        self.assertEqual(response.counts()["analyzed"], 5)

    def test_a_v2_request_refuses_a_v1_answer(self) -> None:
        request = CandidateAnalysisRequest(
            run_id=self.response_raw["run_id"],
            candidate_pool_id=self.extraction.pool.pool_id,
            claim_envelope=self.envelope,
            targets=targets_from_extraction(self.extraction),
            prompt_contract_version=ANALYZER_PROMPT_CONTRACT_VERSION,
            question=prompt_for(ANALYZER_PROMPT_CONTRACT_VERSION),
        )
        response = parse_analysis_response(
            self.response_raw,
            request=request,
            request_text=render_analysis_request(request),
        )
        self.assertIsNotNone(response.response_failure)
        self.assertIn("prompt contract", response.response_failure or "")
        self.assertEqual(response.counts()["analysis_failed"], len(self.extraction.candidates))

    def test_the_stage_renders_the_request_under_the_chosen_contract(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        result = run_candidate_evidence_stage(
            job_root=tmp,
            extraction=self.extraction,
            envelope=self.envelope,
            run_id="analysisrunv1_promptversion",
            prompt_contract_version=ANALYZER_PROMPT_CONTRACT_VERSION,
            response_document=self.response_raw,
        )
        written = json.loads(
            (tmp / producer_registry.CANDIDATE_ANALYSIS_REQUEST_ARTIFACT).read_text()
        )
        self.assertEqual(
            written["prompt_contract_version"], ANALYZER_PROMPT_CONTRACT_VERSION
        )
        self.assertEqual(written["question"], ANALYZER_PROMPT_V2)
        # The v1 fixture answer cannot satisfy a v2 request, and says so.
        self.assertIsNotNone(result.response.response_failure)
        self.assertEqual(len(result.evidence.entries), len(self.extraction.pool.entries))

    def test_an_unknown_prompt_contract_is_refused(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        with self.assertRaises(CandidateAnalysisError):
            run_candidate_evidence_stage(
                job_root=tmp,
                extraction=self.extraction,
                envelope=self.envelope,
                run_id="analysisrunv1_unknown",
                prompt_contract_version="candidate_evidence_prompt.v99",
                response_document=self.response_raw,
            )


class ContactSheetTests(unittest.TestCase):
    def test_the_sheet_lays_tiles_out_in_order(self) -> None:
        import numpy as np

        tiles = [np.full((4, 6, 3), value, dtype=np.uint8) for value in (10, 20, 30, 40, 50)]
        sheet = build_contact_sheet(tiles, gap=2, border=1, max_columns=3)
        self.assertEqual(sheet.shape[1], 3 * (6 + 2) + 2 * 2)
        self.assertEqual(sheet.shape[0], 2 * (4 + 2) + 2)
        self.assertEqual(int(sheet[1, 1, 0]), 10)
        self.assertEqual(int(sheet[1, 11, 0]), 20)
        self.assertEqual(int(sheet[9, 1, 0]), 40)

    def test_tiles_must_share_one_geometry(self) -> None:
        import numpy as np

        with self.assertRaises(FrameEvidenceError):
            build_contact_sheet([np.zeros((4, 4, 3), np.uint8), np.zeros((5, 4, 3), np.uint8)])
        with self.assertRaises(FrameEvidenceError):
            build_contact_sheet([])


@unittest.skipUnless(_has_ffmpeg(), "ffmpeg and ffprobe are required")
class MediaCase(unittest.TestCase):
    """Real clips, a real extraction, and a real evidence document.

    Shared by the frame, audit and direction cases. It holds no tests of its own, so
    nothing runs twice.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = Path(tempfile.mkdtemp())
        cls.clip = build_two_tone_clip(cls.tmp / "two-tone.mp4")

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self) -> None:
        self.job = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.job, ignore_errors=True)

    def extraction_for(self, window: tuple[int, int]):
        material = identify_material(self.clip)
        catalog = IdentityCatalog(
            materials=(MaterialIdentity(material.material_id, material.content_sha256, material.byte_size),),
            candidates=(),
        )
        from src.ai_autocut.timebase_adapter import TimebaseAdapter

        measurement = SourceMeasurement.from_source(
            material_id=material.material_id,
            stream_index=0,
            source=str(self.clip),
            adapter=TimebaseAdapter(fps=30),
        )
        segmentation = SourceSegmentation(
            material_id=material.material_id,
            stream_index=0,
            segments=(SegmentSpan(0, window[0], window[1]),),
        )
        proposals, _ = proposals_from_segmentation(
            segmentation, measurement=measurement
        )
        extraction = extract_candidates(
            catalog=catalog,
            measurements=(measurement,),
            segmentations=(segmentation,),
            proposals=proposals,
        )
        return extraction, measurement, {material.material_id: str(self.clip)}

    def build_evidence(self, claims, *, clip=None):
        from src.ai_autocut.candidate_analysis import (
            CandidateAnalysisRequest,
            build_candidate_evidence,
            parse_analysis_response,
            prompt_for,
            render_analysis_request,
            targets_from_extraction,
        )

        if clip is not None:
            self.clip = clip
        extraction, _, media = self.extraction_for((0, 60))
        bundle = build_frame_evidence(
            run_id="analysisrunv1_audit",
            extraction=extraction,
            media_paths=media,
            job_root=self.job,
            sample_count=6,
        )
        candidate_id = extraction.candidates[0].candidate_id
        envelope = ClaimEnvelope(
            ref="brief/claim_envelope.json",
            sha256=hashlib.sha256(b"audit-envelope").hexdigest(),
            facts=(ClaimFact("fact_surface_state_change_visible", "the surface changes"),),
        )
        request = CandidateAnalysisRequest(
            run_id="analysisrunv1_audit",
            candidate_pool_id=extraction.pool.pool_id,
            claim_envelope=envelope,
            targets=targets_from_extraction(extraction),
        )
        response = {
            "schema_version": "candidate_analysis_response.v1",
            "run_id": "analysisrunv1_audit",
            "candidate_pool_id": extraction.pool.pool_id,
            "provider": "offline_audit",
            "model": "offline_audit",
            "prompt_contract_version": request.prompt_contract_version,
            "request": {
                "ref": producer_registry.CANDIDATE_ANALYSIS_REQUEST_ARTIFACT,
                "sha256": hashlib.sha256(
                    render_analysis_request(request).encode()
                ).hexdigest(),
            },
            "entries": [
                {
                    "candidate_id": candidate_id,
                    "status": "ANALYZED",
                    "observations": {
                        "visible_action": "a region of the frame changes brightness",
                        "visible_result": "the change is held to the end of the window",
                        "product_visibility": "NOT_VISIBLE",
                        "usage_context": "UNKNOWN",
                        "body_area": "NOT_APPLICABLE",
                        "visual_usability": "USABLE",
                        "claim_support_class": "DIRECT_DEMONSTRATION",
                    },
                    "action_evidence": [],
                    "claims": claims(candidate_id),
                    "evidence_type": "DIRECT_DEMONSTRATION",
                    "confidence": 0.5,
                    "provenance": [{"start_frame": 0, "end_frame_exclusive": 60}],
                    "role_affinities": [],
                    "risks": [],
                    "rationale": "a measurable brightness change across the window",
                }
            ],
        }
        parsed = parse_analysis_response(
            response,
            request=request,
            request_text=render_analysis_request(request),
        )
        evidence = build_candidate_evidence(
            request=request, response=parsed, extraction=extraction
        )
        return evidence, bundle, media, candidate_id

@unittest.skipUnless(_has_ffmpeg(), "ffmpeg and ffprobe are required")
class FrameEvidenceTests(MediaCase):
    def test_frames_are_labelled_bound_and_hashed(self) -> None:
        extraction, measurement, media = self.extraction_for((0, 60))
        bundle = build_frame_evidence(
            run_id="analysisrunv1_offline",
            extraction=extraction,
            media_paths=media,
            job_root=self.job,
            sample_count=6,
        )
        candidate = bundle.candidates[0]
        expected = sample_frame_indices(0, 60, 6)
        self.assertEqual(
            [frame.source_frame for frame in candidate.frames], list(expected)
        )
        for frame in candidate.frames:
            path = self.job / frame.image_relpath
            self.assertTrue(path.is_file())
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest(), frame.sha256
            )
            # The image is named by its exact decoded source frame.
            self.assertIn(f"f{frame.source_frame:06d}.png", frame.image_relpath)
        sheet = candidate.contact_sheet
        self.assertIsNotNone(sheet)
        assert sheet is not None
        self.assertEqual(sheet.tile_frames, expected)
        self.assertTrue((self.job / sheet.image_relpath).is_file())
        self.assertEqual(
            hashlib.sha256((self.job / sheet.image_relpath).read_bytes()).hexdigest(),
            sheet.sha256,
        )

    def test_the_manifest_round_trips_and_is_exact_key(self) -> None:
        extraction, _, media = self.extraction_for((0, 60))
        bundle = build_frame_evidence(
            run_id="analysisrunv1_offline",
            extraction=extraction,
            media_paths=media,
            job_root=self.job,
            sample_count=4,
        )
        raw = render_frame_evidence(bundle)
        self.assertEqual(render_frame_evidence(parse_frame_evidence(json.loads(raw))), raw)
        payload = json.loads(raw)
        payload["candidates"][0]["confidence"] = 0.5
        with self.assertRaises(FrameEvidenceError):
            parse_frame_evidence(payload)
        payload = json.loads(raw)
        del payload["candidates"][0]["frames"][0]["source_frame"]
        with self.assertRaises(FrameEvidenceError):
            parse_frame_evidence(payload)

    def test_a_missing_source_is_refused_not_skipped(self) -> None:
        extraction, _, _ = self.extraction_for((0, 60))
        with self.assertRaises(FrameEvidenceError):
            build_frame_evidence(
                run_id="analysisrunv1_offline",
                extraction=extraction,
                media_paths={},
                job_root=self.job,
            )

    def test_the_manifest_is_written_where_the_registry_says(self) -> None:
        extraction, _, media = self.extraction_for((0, 60))
        build_frame_evidence(
            run_id="analysisrunv1_offline",
            extraction=extraction,
            media_paths=media,
            job_root=self.job,
            sample_count=4,
        )
        self.assertTrue((self.job / FRAME_EVIDENCE_ARTIFACT).is_file())
        self.assertEqual(
            FRAME_EVIDENCE_ARTIFACT,
            producer_registry.CANDIDATE_FRAME_EVIDENCE_ARTIFACT,
        )


@unittest.skipUnless(_has_ffmpeg(), "ffmpeg and ffprobe are required")
class EvidenceTruthTests(unittest.TestCase):
    """Contract validity and evidence truth are separate axes.

    Phase 2.5 proved a document can satisfy every contract rule and still assert
    something the footage does not show. These tests hold that distinction: the
    contract verdict is untouched by the audit, and the audit never silently
    promotes an unchecked assertion to true.
    """

    def audit(self, *, direct: int, verified: int, unverified: int, failed: int):
        """A synthetic v2 document and the audit that measured it."""

        entries = []
        findings = []
        facts = []
        index = 0
        for kind, count in (
            ("verified", verified),
            ("unverified", unverified),
            ("failed", failed),
        ):
            for _ in range(count):
                index += 1
                candidate_id = f"candv1_{index:064d}"
                fact_ref = f"fact_{kind}_{index}"
                facts.append(fact_ref)
                base = CandidateEvidenceEntry(
                    candidate_id=candidate_id,
                    status=EvidenceStatus.ANALYZED,
                    rationale="prose that must not matter",
                    observations=Observations(
                        visible_action="something happens",
                        visible_result="a state is left behind",
                        product_visibility="PARTIAL",
                        usage_context="IN_USE",
                        body_area="HANDS",
                        visual_usability="USABLE",
                        claim_support_class="DIRECT_DEMONSTRATION",
                    ),
                    action_evidence=(ActionEvidence(1, 2, 5, 8),),
                    claims=(
                        ClaimSupportRecord(
                            product_fact_ref=fact_ref,
                            support=ClaimSupport.DIRECT,
                            provenance=(SourceRange(1, 8),),
                        ),
                    ),
                    evidence_type=EvidenceType.DIRECT_DEMONSTRATION,
                    confidence=0.5,
                    provenance=(SourceRange(1, 8),),
                    role_affinities=(),
                    risks=(),
                )
                entries.append(
                    CandidateEvidenceEntryV2(
                        base=base,
                        observations=ObservationsV2(
                            base=base.observations,  # type: ignore[arg-type]
                            action_presence=ActionPresence.ACTION_PRESENT,
                            observable_states=(ObservableState.STATE_CHANGE_VISIBLE,),
                        ),
                    )
                )
                if kind != "unverified":
                    findings.append(
                        ProvenanceFinding(
                            check=ProvenanceCheck(
                                candidate_id=candidate_id,
                                product_fact_ref=fact_ref,
                                before_frame=1,
                                after_frame=7,
                                expectation=ChangeDirection.INCREASE,
                                min_delta=10.0,
                            ),
                            measured_before=1.0,
                            measured_after=99.0,
                            delta=98.0,
                            verdict=(
                                AuditVerdict.PASS
                                if kind == "verified"
                                else AuditVerdict.FAIL
                            ),
                            detail="measured against the media",
                        )
                    )
        evidence = CandidateEvidenceV2(
            candidate_pool_id="poolv1_" + "a" * 64,
            product_facts=ProductFacts(
                "brief/product_facts.json", "b" * 64, tuple(facts) or ("fact_none",)
            ),
            analysis_run=AnalysisRun("run", "provider", "model", "prompt.v1"),
            entries=tuple(entries),
        )
        audit = FrameAudit(
            findings=tuple(findings),
            direct_claims=direct,
            direct_claims_with_supplied_frame=direct,
            content_checks_passed=verified,
            content_checks_failed=failed,
        )
        return evidence, audit

    def test_a_measured_pass_is_verified(self) -> None:
        evidence, audit = self.audit(direct=1, verified=1, unverified=0, failed=0)
        truth = declared_check_status(evidence, audit)
        self.assertIs(truth.status, CheckStatus.CHECKS_PASSED)
        self.assertTrue(truth.ok)
        self.assertEqual(truth.checked_direct_claims, 1)

    def test_an_unchecked_assertion_is_not_verified_rather_than_true(self) -> None:
        evidence, audit = self.audit(direct=1, verified=0, unverified=1, failed=0)
        truth = declared_check_status(evidence, audit)
        self.assertIs(truth.status, CheckStatus.NOT_VERIFIED)
        self.assertFalse(truth.ok)
        self.assertEqual(len(truth.unverified_direct_claims), 1)
        self.assertIn("no declared check measured", truth.detail)

    def test_a_failed_check_fails_evidence_truth(self) -> None:
        evidence, audit = self.audit(direct=1, verified=0, unverified=0, failed=1)
        truth = declared_check_status(evidence, audit)
        self.assertIs(truth.status, CheckStatus.CHECKS_FAILED)
        self.assertEqual(len(truth.failed_direct_claims), 1)

    def test_a_failed_audit_does_not_touch_the_claim_envelope(self) -> None:
        evidence, audit = self.audit(direct=1, verified=0, unverified=0, failed=1)
        before = (evidence.product_facts.ref, evidence.product_facts.sha256, evidence.product_facts.allowed_fact_refs)
        before_claims = tuple(
            (e.candidate_id, tuple(c.product_fact_ref for c in (e.claims or ())))
            for e in evidence.entries
        )
        truth = declared_check_status(evidence, audit)
        self.assertIs(truth.status, CheckStatus.CHECKS_FAILED)
        after = (evidence.product_facts.ref, evidence.product_facts.sha256, evidence.product_facts.allowed_fact_refs)
        after_claims = tuple(
            (e.candidate_id, tuple(c.product_fact_ref for c in (e.claims or ())))
            for e in evidence.entries
        )
        self.assertEqual(before, after)
        self.assertEqual(before_claims, after_claims)

    def test_the_truth_report_is_serialisable_and_states_its_counts(self) -> None:
        evidence, audit = self.audit(direct=2, verified=1, unverified=1, failed=0)
        document = declared_check_status(evidence, audit).as_dict()
        self.assertEqual(document["declared_check_status"], "NOT_VERIFIED")
        self.assertEqual(document["scope"], CHECK_SCOPE)
        self.assertEqual(document["direct_claims"], 2)
        self.assertEqual(document["checked_direct_claims"], 1)
        self.assertIn("detail", document)

    def test_no_direct_assertion_is_vacuously_verified(self) -> None:
        evidence, audit = self.audit(direct=0, verified=0, unverified=0, failed=0)
        truth = declared_check_status(evidence, audit)
        self.assertIs(truth.status, CheckStatus.CHECKS_PASSED)
        self.assertIn("no DIRECT assertion", truth.detail)


class FrameAuditTests(MediaCase):
    """The audit against a clip whose real brightness change is known."""

    def test_a_real_change_passes_and_a_claim_of_no_change_fails(self) -> None:
        claims = lambda candidate_id: [
            {
                "product_fact_ref": "fact_surface_state_change_visible",
                "support": "DIRECT",
                "provenance": [{"start_frame": 0, "end_frame_exclusive": 60}],
                "note": "the region changes from dark to light",
            }
        ]
        evidence, bundle, media, _ = self.build_evidence(claims)
        candidate_id = bundle.candidates[0].candidate_id

        directional = ProvenanceCheck(
            candidate_id=candidate_id,
            product_fact_ref="fact_surface_state_change_visible",
            kind=FrameCheckKind.MEAN_LUMINANCE_CHANGE,
            before_frame=5,
            after_frame=50,
            expectation=ChangeDirection.INCREASE,
            min_delta=80.0,
            roi=RegionOfInterest(0.2, 0.2, 0.6, 0.6),
            description="the region is black early in the clip and white later",
        )
        magnitude = ProvenanceCheck(
            candidate_id=candidate_id,
            product_fact_ref="fact_surface_state_change_visible",
            kind=FrameCheckKind.ROI_LUMINANCE_SPAN,
            window=(0, 60),
            expectation=ChangeDirection.ANY,
            min_delta=80.0,
            roi=RegionOfInterest(0.2, 0.2, 0.6, 0.6),
            description="the region spans black to white somewhere in the window",
        )
        audit = audit_frame_provenance(
            evidence=evidence,
            bundle=bundle,
            media_paths=media,
            checks=(directional, magnitude),
            job_root=self.job,
        )
        self.assertTrue(audit.ok)
        self.assertEqual(audit.direct_claims, 1)
        self.assertEqual(audit.direct_claims_with_supplied_frame, 1)
        self.assertEqual(audit.content_checks_passed, 2)
        self.assertGreater(audit.findings[0].delta or 0, 80.0)
        extremes = audit.findings[1].extreme_frames
        self.assertIsNotNone(extremes)
        assert extremes is not None
        self.assertLess(extremes[0], 30)
        self.assertGreaterEqual(extremes[1], 30)

        impossibly_strict = ProvenanceCheck(
            candidate_id=candidate_id,
            product_fact_ref="fact_surface_state_change_visible",
            kind=FrameCheckKind.MEAN_LUMINANCE_CHANGE,
            before_frame=5,
            after_frame=50,
            expectation=ChangeDirection.INCREASE,
            min_delta=300.0,
            roi=RegionOfInterest(0.2, 0.2, 0.6, 0.6),
            description="an expectation no clip can satisfy: mean luminance cannot move by more than 255",
        )
        audit = audit_frame_provenance(
            evidence=evidence,
            bundle=bundle,
            media_paths=media,
            checks=(impossibly_strict,),
            job_root=self.job,
        )
        self.assertFalse(audit.ok)
        self.assertEqual(audit.content_checks_failed, 1)

    def test_a_direct_claim_about_frames_nobody_saw_is_flagged(self) -> None:
        claims = lambda candidate_id: [
            {
                "product_fact_ref": "fact_surface_state_change_visible",
                "support": "DIRECT",
                "provenance": [{"start_frame": 2, "end_frame_exclusive": 6}],
                "note": "cites only frames the sample skipped",
            }
        ]
        evidence, bundle, media, _ = self.build_evidence(claims)
        audit = audit_frame_provenance(
            evidence=evidence, bundle=bundle, media_paths=media, checks=(), job_root=self.job
        )
        self.assertFalse(audit.ok)
        self.assertEqual(len(audit.direct_claims_without_supplied_frame), 1)
        self.assertEqual(audit.direct_claims_with_supplied_frame, 0)

    def test_a_tampered_image_is_detected(self) -> None:
        claims = lambda candidate_id: [
            {
                "product_fact_ref": "fact_surface_state_change_visible",
                "support": "DIRECT",
                "provenance": [{"start_frame": 0, "end_frame_exclusive": 60}],
                "note": "ok",
            }
        ]
        evidence, bundle, media, _ = self.build_evidence(claims)
        target = self.job / bundle.candidates[0].frames[0].image_relpath
        target.write_bytes(target.read_bytes() + b"\x00")
        audit = audit_frame_provenance(
            evidence=evidence, bundle=bundle, media_paths=media, checks=(), job_root=self.job
        )
        self.assertFalse(audit.ok)
        self.assertTrue(audit.frames_missing_or_changed)

    def test_a_check_without_its_frames_is_refused(self) -> None:
        with self.assertRaises(FrameEvidenceError):
            ProvenanceCheck(
                candidate_id="c",
                product_fact_ref="f",
                expectation=ChangeDirection.INCREASE,
                min_delta=1.0,
            )
        with self.assertRaises(FrameEvidenceError):
            ProvenanceCheck(
                candidate_id="c",
                product_fact_ref="f",
                kind=FrameCheckKind.ROI_LUMINANCE_SPAN,
                expectation=ChangeDirection.ANY,
                min_delta=1.0,
            )

    def test_a_span_may_not_claim_a_direction(self) -> None:
        """A magnitude has no temporal order, so it cannot answer a direction."""

        for expectation in (ChangeDirection.INCREASE, ChangeDirection.DECREASE):
            with self.subTest(expectation=expectation):
                with self.assertRaisesRegex(FrameEvidenceError, "magnitude, not direction"):
                    ProvenanceCheck(
                        candidate_id="c",
                        product_fact_ref="f",
                        kind=FrameCheckKind.ROI_LUMINANCE_SPAN,
                        window=(0, 10),
                        expectation=expectation,
                        min_delta=1.0,
                    )


class DirectionTests(MediaCase):
    """Direction in time, both ways round, on real clips.

    The defect this closes: a sweep that reported ``max - min`` was answering a
    directional question, so a clip that got steadily *darker* passed a declared
    ``INCREASE``. Direction is now asserted only where the frames have an order.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = Path(tempfile.mkdtemp())
        cls.clip = _build_tone_clip(cls.tmp / "dark-then-light.mp4", "black", "white")
        cls.dark_then_light = cls.clip
        cls.light_then_dark = _build_tone_clip(
            cls.tmp / "light-then-dark.mp4", "white", "black"
        )

    def verdict(self, clip: Path, expectation, *, kind=None, before=5, after=50):
        evidence, bundle, media, _ = self.build_evidence(
            lambda candidate_id: [
                {
                    "product_fact_ref": "fact_surface_state_change_visible",
                    "support": "DIRECT",
                    "provenance": [{"start_frame": 0, "end_frame_exclusive": 60}],
                    "note": "the region changes across the clip",
                }
            ],
            clip=clip,
        )
        if kind is None:
            kind = FrameCheckKind.MEAN_LUMINANCE_CHANGE
        check = ProvenanceCheck(
            candidate_id=bundle.candidates[0].candidate_id,
            product_fact_ref="fact_surface_state_change_visible",
            kind=kind,
            before_frame=before if kind is FrameCheckKind.MEAN_LUMINANCE_CHANGE else None,
            after_frame=after if kind is FrameCheckKind.MEAN_LUMINANCE_CHANGE else None,
            window=(0, 60) if kind is FrameCheckKind.ROI_LUMINANCE_SPAN else None,
            expectation=expectation,
            min_delta=100.0,
            roi=RegionOfInterest(0.25, 0.25, 0.5, 0.5),
            description="a real tone change between two named frames",
        )
        audit = audit_frame_provenance(
            evidence=evidence, bundle=bundle, media_paths=media, checks=(check,), job_root=self.job
        )
        return audit.findings[0]

    def test_dark_to_light_passes_increase_and_fails_decrease(self) -> None:
        self.assertIs(
            self.verdict(self.dark_then_light, ChangeDirection.INCREASE).verdict,
            AuditVerdict.PASS,
        )
        failed = self.verdict(self.dark_then_light, ChangeDirection.DECREASE)
        self.assertIs(failed.verdict, AuditVerdict.FAIL)
        self.assertGreater(failed.delta or 0, 100.0)

    def test_light_to_dark_passes_decrease_and_fails_increase(self) -> None:
        self.assertIs(
            self.verdict(self.light_then_dark, ChangeDirection.DECREASE).verdict,
            AuditVerdict.PASS,
        )
        failed = self.verdict(self.light_then_dark, ChangeDirection.INCREASE)
        self.assertIs(failed.verdict, AuditVerdict.FAIL)
        self.assertLess(failed.delta or 0, -100.0)

    def test_a_flat_clip_is_stable_and_moves_neither_way(self) -> None:
        evidence, bundle, media, _ = self.build_evidence(
            lambda candidate_id: [
                {
                    "product_fact_ref": "fact_surface_state_change_visible",
                    "support": "DIRECT",
                    "provenance": [{"start_frame": 0, "end_frame_exclusive": 60}],
                    "note": "one tone throughout",
                }
            ],
            clip=_build_tone_clip(self.tmp / "flat.mp4", "gray", "gray"),
        )
        candidate_id = bundle.candidates[0].candidate_id
        # A clip that never changes must satisfy STABLE and must fail a claim that
        # something moved: the same magnitude, read both ways.
        for expectation, min_delta, expected in (
            (ChangeDirection.STABLE, 40.0, AuditVerdict.PASS),
            (ChangeDirection.ANY, 40.0, AuditVerdict.FAIL),
        ):
            check = ProvenanceCheck(
                candidate_id=candidate_id,
                product_fact_ref="fact_surface_state_change_visible",
                kind=FrameCheckKind.ROI_LUMINANCE_SPAN,
                window=(0, 60),
                expectation=expectation,
                min_delta=min_delta,
                roi=RegionOfInterest(0.25, 0.25, 0.5, 0.5),
                description="a span tolerance the run has to choose honestly",
            )
            audit = audit_frame_provenance(
                evidence=evidence, bundle=bundle, media_paths=media, checks=(check,), job_root=self.job
            )
            with self.subTest(min_delta=min_delta):
                self.assertIs(audit.findings[0].verdict, expected)

    def test_a_span_verdict_states_that_it_makes_no_directional_claim(self) -> None:
        finding = self.verdict(
            self.dark_then_light, ChangeDirection.ANY, kind=FrameCheckKind.ROI_LUMINANCE_SPAN
        )
        self.assertIs(finding.verdict, AuditVerdict.PASS)
        self.assertIn("no claim about direction in time", finding.detail)


if __name__ == "__main__":
    unittest.main()
