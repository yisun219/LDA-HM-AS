from __future__ import annotations

import os
import unittest
from unittest import mock

from lda_hm import SandboxUnavailable
from lda_hm.driver import _resolve_template, connect_sandbox
from lda_hm.execution import _raise_setup_failure
from lda_hm.sandbox import SandboxResult, _condense_gateway_error


class _EnvGuard(unittest.TestCase):
    """Restore the template knobs so ordering cannot leak between tests."""

    KEYS = ("E2B_TEMPLATE", "LDA_ALLOW_TEMPLATE_OVERRIDE")

    def setUp(self) -> None:
        self._saved = {key: os.environ.get(key) for key in self.KEYS}
        for key in self.KEYS:
            os.environ.pop(key, None)

    def tearDown(self) -> None:
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class TemplateProvenanceTest(_EnvGuard):
    def test_card_template_used_when_unset(self) -> None:
        self.assertEqual(_resolve_template("lda-base", log=lambda _: None), "lda-base")

    def test_matching_override_is_not_a_divergence(self) -> None:
        os.environ["E2B_TEMPLATE"] = "lda-base"
        self.assertEqual(_resolve_template("lda-base", log=lambda _: None), "lda-base")

    def test_silent_divergence_is_refused(self) -> None:
        os.environ["E2B_TEMPLATE"] = "codex-hello-world"
        with self.assertRaises(SandboxUnavailable):
            _resolve_template("lda-base", log=lambda _: None)

    def test_acknowledged_override_is_allowed_and_logged(self) -> None:
        os.environ["E2B_TEMPLATE"] = "codex-hello-world"
        os.environ["LDA_ALLOW_TEMPLATE_OVERRIDE"] = "1"
        lines: list[str] = []
        resolved = _resolve_template("lda-base", log=lines.append)
        self.assertEqual(resolved, "codex-hello-world")
        self.assertTrue(any("template override" in line for line in lines))


class GatewayErrorCondensationTest(unittest.TestCase):
    def test_html_error_page_is_reduced_to_one_line(self) -> None:
        raw = RuntimeError("502: <!DOCTYPE html><html><title>502</title>" + "x" * 9000)
        condensed = _condense_gateway_error(raw)
        self.assertIn("502", condensed)
        self.assertNotIn("DOCTYPE", condensed)
        self.assertLessEqual(len(condensed), 200)

    def test_plain_message_survives(self) -> None:
        self.assertEqual(_condense_gateway_error(RuntimeError("connection reset")), "connection reset")

    def test_empty_message_falls_back_to_type_name(self) -> None:
        self.assertEqual(_condense_gateway_error(TimeoutError("")), "TimeoutError")


class SetupFailureClassificationTest(unittest.TestCase):
    def test_transport_exit_is_infrastructure(self) -> None:
        result = SandboxResult(
            ("install-test-tools",),
            125,
            "",
            "RemoteProtocolError('server disconnected')",
            1.0,
            "e2b-test",
        )
        with self.assertRaises(SandboxUnavailable):
            _raise_setup_failure(("install-test-tools",), result)

    def test_real_setup_exit_remains_a_defect(self) -> None:
        result = SandboxResult(
            ("build-package",), 2, "", "compiler error", 1.0, "e2b-test"
        )
        with self.assertRaises(RuntimeError):
            _raise_setup_failure(("build-package",), result)


class BootstrapWaitTest(_EnvGuard):
    """Bootstrap must treat a 502-ing gateway as infrastructure, not a verdict."""

    def test_retries_then_gives_up_without_killing_on_first_failure(self) -> None:
        attempts = {"n": 0}

        def _fail(**_: object) -> object:
            attempts["n"] += 1
            raise SandboxUnavailable("E2B gateway could not create a sandbox: 502")

        with mock.patch.dict(
            os.environ,
            {"LDA_GATEWAY_WAIT_SECONDS": "3", "LDA_GATEWAY_BACKOFF_CAP": "1"},
        ), mock.patch("lda_hm.driver.E2BSandbox.connect", side_effect=_fail), mock.patch(
            "lda_hm.driver.time.sleep"
        ) as sleep:
            with self.assertRaises(SandboxUnavailable):
                connect_sandbox("lda-base", log=lambda _: None)
        self.assertGreater(attempts["n"], 1, "bootstrap gave up on the first 502")
        self.assertTrue(sleep.called, "bootstrap did not back off between attempts")

    def test_recovers_when_gateway_returns(self) -> None:
        calls = {"n": 0}
        sentinel = object()

        def _flaky(**_: object) -> object:
            calls["n"] += 1
            if calls["n"] < 3:
                raise SandboxUnavailable("502")
            return sentinel

        with mock.patch("lda_hm.driver.E2BSandbox.connect", side_effect=_flaky), mock.patch(
            "lda_hm.driver.time.sleep"
        ):
            self.assertIs(connect_sandbox("lda-base", log=lambda _: None), sentinel)
        self.assertEqual(calls["n"], 3)


if __name__ == "__main__":
    unittest.main()
