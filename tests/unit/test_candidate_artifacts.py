import hashlib
import json
import tempfile
import unittest

from lda.agents.factory import AgentFactory
from lda.artifacts.store import ArtifactStore
from lda.e2b.client import E2BClient
from lda.humanize.mission import HumanizeMission
from lda.models import Candidate, Mission, WorldState
from lda.state.store import EventStore


class CandidateArtifactTest(unittest.TestCase):
    def test_content_addressed_store_deduplicates_and_verifies(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ArtifactStore(tmp)
            first = store.put("first.deb", b"same package")
            second = store.put("renamed.deb", b"same package")
            self.assertEqual(first, second)
            self.assertTrue(first.startswith("sha256:"))
            self.assertEqual(store.get(first), b"same package")
            store.path(first).write_bytes(b"corrupt")
            with self.assertRaisesRegex(RuntimeError, "hash mismatch"):
                store.get(first)

    def test_candidate_debs_and_build_evidence_leave_sandbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = E2BClient(fake=True)
            work = client.create({"run_id": "r"})
            runtime_path = "/workspace/build/runtime.deb"
            dev_path = "/workspace/build/dev.deb"
            runtime = b"runtime-deb"
            dev = b"dev-deb"
            client.filesystem_write(work, runtime_path, runtime)
            client.filesystem_write(work, dev_path, dev)
            candidate = Candidate("candidate-1", "mission-1")
            world = WorldState("r", candidates=[candidate])
            mission = HumanizeMission(
                world, Mission("mission-1", "libgtk-4-1", 1.0),
                AgentFactory(client), ArtifactStore(tmp))
            evidence = {
                "passed": True,
                "runtime_artifact": runtime_path,
                "dev_artifacts": {"libgtk-4-dev": dev_path},
                "artifacts": [
                    {"path": runtime_path, "sha256": hashlib.sha256(runtime).hexdigest()},
                    {"path": dev_path, "sha256": hashlib.sha256(dev).hexdigest()},
                ],
            }
            refs = mission._persist_candidate_artifacts(candidate, work, evidence, {})
            recovered_store = ArtifactStore(tmp)
            self.assertEqual(recovered_store.get(refs["runtime"]), runtime)
            self.assertEqual(recovered_store.get(refs["dev:libgtk-4-dev"]), dev)
            persisted_evidence = json.loads(recovered_store.get(refs["build_evidence"]))
            self.assertTrue(persisted_evidence["passed"])
            self.assertEqual(candidate.artifact_refs, refs)
            self.assertEqual(candidate.evidence_refs, [refs["build_evidence"]])

    def test_event_replays_candidate_refs_after_controller_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = ArtifactStore(tmp)
            deb_ref = artifacts.put("candidate.deb", b"candidate")
            evidence_ref = artifacts.put("build.json", b"{}")
            store = EventStore(tmp)
            store.save_world(WorldState(
                "r", candidates=[Candidate("candidate-1", "mission-1", status="ACTIVE")]))
            candidate = Candidate(
                "candidate-1", "mission-1", status="REJECTED",
                artifact_refs={"runtime": deb_ref, "build_evidence": evidence_ref},
                evidence_refs=[evidence_ref],
            )
            store.append(
                "r", "1", "candidate-builder", "CANDIDATE_ARTIFACTS",
                output_refs=[deb_ref, evidence_ref],
                payload={"candidate": candidate.__dict__},
            )
            recovered = EventStore(tmp).recover()
            self.assertEqual(len(recovered.candidates), 1)
            self.assertEqual(recovered.candidates[0].status, "REJECTED")
            self.assertEqual(recovered.candidates[0].artifact_refs["runtime"], deb_ref)
            self.assertEqual(ArtifactStore(tmp).get(deb_ref), b"candidate")
            event = EventStore(tmp).events()[-1]
            self.assertEqual(event["output_refs"], [deb_ref, evidence_ref])


if __name__ == "__main__":
    unittest.main()
