# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""
Release workflow YAML structure tests (REL-01, REL-02, REL-03).

Verifies that .github/workflows/release.yml contains the structural requirements
that guarantee correct release behaviour without actually running the CI pipeline.
"""

import pathlib

import yaml

REPO_ROOT = pathlib.Path(__file__).parent.parent.parent
RELEASE_YML = REPO_ROOT / ".github" / "workflows" / "release.yml"


def _load_workflow() -> dict:
    return yaml.safe_load(RELEASE_YML.read_text())


def _workflow_on(data: dict) -> dict:
    """Return the 'on' trigger block.

    yaml.safe_load (YAML 1.1) converts bare 'on' to the Python boolean True,
    so we must look up the True key, not the string 'on'.
    """
    # Try boolean True first (yaml.safe_load behaviour), then string 'on' as fallback.
    return data.get(True) or data.get("on") or {}


def _step_names(job: dict) -> list[str]:
    return [step.get("name", "") for step in job.get("steps", [])]


def _step_runs(job: dict) -> list[str]:
    return [step.get("run", "") for step in job.get("steps", []) if "run" in step]


class TestReleaseWorkflowExists:
    def test_release_yml_exists(self):
        """Workflow file must be present."""
        assert RELEASE_YML.is_file(), f"{RELEASE_YML} not found"

    def test_release_yml_is_valid_yaml(self):
        """Workflow file must parse as valid YAML."""
        data = _load_workflow()
        assert isinstance(data, dict), "release.yml did not parse as a YAML mapping"


class TestWorkflowTriggerAndConcurrency:
    def test_workflow_triggers_on_version_tag_push(self):
        """REL-01/REL-02: Workflow must fire on 'v*' tag push."""
        data = _load_workflow()
        tags = _workflow_on(data).get("push", {}).get("tags", [])
        assert any(t.startswith("v") for t in tags), f"No 'v*' tag trigger found in workflow on.push.tags: {tags}"

    def test_concurrency_block_exists_at_workflow_level(self):
        """REL-01/REL-02: Top-level concurrency block prevents duplicate release runs."""
        data = _load_workflow()
        assert "concurrency" in data, "No top-level 'concurrency' key in release.yml"

    def test_concurrency_cancel_in_progress_is_false(self):
        """REL-01: In-progress release must not be cancelled — cancel-in-progress must be false."""
        data = _load_workflow()
        concurrency = data.get("concurrency", {})
        assert concurrency.get("cancel-in-progress") is False, (
            f"concurrency.cancel-in-progress is not false: {concurrency}"
        )


class TestValidateVersionsJob:
    def test_validate_versions_job_exists(self):
        """REL-01/REL-02: validate-versions job must exist."""
        data = _load_workflow()
        assert "validate-versions" in data.get("jobs", {}), "No 'validate-versions' job found in release.yml"

    def test_build_job_needs_validate_versions(self):
        """REL-01/REL-02: build job must declare a 'needs' dependency on validate-versions."""
        data = _load_workflow()
        build_job = data.get("jobs", {}).get("build", {})
        needs = build_job.get("needs", [])
        if isinstance(needs, str):
            needs = [needs]
        assert "validate-versions" in needs, f"build job 'needs' does not include 'validate-versions': {needs}"

    def test_validate_versions_checks_five_platform_packages(self):
        """REL-02: Version validation loop must reference all 5 platform packages."""
        data = _load_workflow()
        job = data["jobs"]["validate-versions"]
        all_runs = "\n".join(_step_runs(job))
        expected_pkgs = [
            "fwd-darwin-arm64",
            "fwd-darwin-x64",
            "fwd-linux-arm64",
            "fwd-linux-x64",
            "fwd-win32-x64",
        ]
        for pkg in expected_pkgs:
            assert pkg in all_runs, f"Platform package '{pkg}' not referenced in validate-versions run steps"


class TestPublishPypiJob:
    def test_publish_pypi_job_exists(self):
        """REL-01: publish-pypi job must exist."""
        data = _load_workflow()
        assert "publish-pypi" in data.get("jobs", {}), "No 'publish-pypi' job found in release.yml"

    def test_publish_pypi_has_environment_pypi(self):
        """REL-01: publish-pypi job must use 'environment: pypi' for OIDC trusted publishing."""
        data = _load_workflow()
        job = data["jobs"]["publish-pypi"]
        env = job.get("environment")
        assert env == "pypi", f"publish-pypi job environment is {env!r}, expected 'pypi'"

    def test_publish_pypi_has_twine_check_strict(self):
        """REL-01: Dist artifacts must be validated with 'twine check --strict' before publish."""
        data = _load_workflow()
        job = data["jobs"]["publish-pypi"]
        all_runs = "\n".join(_step_runs(job))
        assert "twine check --strict" in all_runs, "No 'twine check --strict' command found in publish-pypi steps"


class TestSbomSteps:
    def _publish_job(self) -> dict:
        data = _load_workflow()
        # SBOM steps live in publish-and-release
        return data["jobs"]["publish-and-release"]

    def test_install_cyclonedx_cli_step_exists(self):
        """REL-03: cyclonedx-cli must be installed in the workflow."""
        job = self._publish_job()
        names = _step_names(job)
        assert any("cyclonedx" in n.lower() for n in names), (
            f"No cyclonedx-cli install step found in publish-and-release job. Steps: {names}"
        )

    def test_cyclonedx_cli_pinned_to_v0_31_0(self):
        """REL-03: cyclonedx-cli download must be pinned to v0.31.0 for reproducibility."""
        job = self._publish_job()
        all_runs = "\n".join(_step_runs(job))
        assert "v0.31.0" in all_runs, "cyclonedx-cli version pin v0.31.0 not found in publish-and-release run steps"

    def test_sha256sum_verification_for_cyclonedx_cli(self):
        """REL-03: cyclonedx-cli binary must be verified with sha256sum after download."""
        job = self._publish_job()
        all_runs = "\n".join(_step_runs(job))
        assert "sha256sum" in all_runs, "No sha256sum verification found for cyclonedx-cli download"

    def test_generate_python_sbom_step_exists(self):
        """REL-03: Python SBOM generation step must be present."""
        job = self._publish_job()
        names = _step_names(job)
        assert any("python sbom" in n.lower() for n in names), f"No 'Generate Python SBOM' step found. Steps: {names}"

    def test_generate_npm_sbom_step_exists(self):
        """REL-03: npm SBOM generation step must be present."""
        job = self._publish_job()
        names = _step_names(job)
        assert any("npm sbom" in n.lower() for n in names), f"No 'Generate npm SBOM' step found. Steps: {names}"

    def test_merge_sboms_step_exists(self):
        """REL-03: SBOM merge step must be present."""
        job = self._publish_job()
        names = _step_names(job)
        assert any("merge" in n.lower() for n in names), f"No 'Merge SBOMs' step found. Steps: {names}"

    def test_sbom_merge_uses_output_version_v1_5(self):
        """REL-03: Merged SBOM must use CycloneDX 1.5 (--output-version v1_5)."""
        job = self._publish_job()
        all_runs = "\n".join(_step_runs(job))
        assert "output-version v1_5" in all_runs or "--output-version v1_5" in all_runs, (
            "CycloneDX 1.5 flag '--output-version v1_5' not found in SBOM merge step"
        )

    def test_cert_pfx_cleanup_uses_trap(self):
        """REL-03 / security: cert.pfx cleanup must use 'trap' to guarantee deletion on error."""
        data = _load_workflow()
        # trap is in the sign-windows job
        sign_win_job = data["jobs"].get("sign-windows", {})
        all_runs = "\n".join(_step_runs(sign_win_job))
        assert "trap" in all_runs, "No 'trap' command found in sign-windows job — cert.pfx cleanup is not guaranteed"
