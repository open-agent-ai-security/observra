# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""
RELEASING.md documentation tests (REL-01, REL-02).

Verifies the operator runbook contains all required sections and critical content
so that a first-time releaser can execute without missing safety steps.
"""
import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).parent.parent.parent
RELEASING_MD = REPO_ROOT / "docs" / "RELEASING.md"

REQUIRED_H2_SECTIONS = [
    "Pre-Tag Checklist",
    "Version Bump Procedure",
    "Tag Push Flow",
    "Post-Publish Verification",
    "Rollback Procedure",
    "Version History Note",
]

ROLLBACK_COMMANDS = [
    "npm unpublish",
    "twine yank",
    "gh release delete",
    "git tag -d",
]


def _content() -> str:
    return RELEASING_MD.read_text()


class TestReleasingMdExists:
    def test_releasing_md_exists(self):
        """REL-01/REL-02: docs/RELEASING.md must exist."""
        assert RELEASING_MD.is_file(), f"{RELEASING_MD} not found"


class TestReleasingMdSections:
    def test_pre_tag_checklist_section_exists(self):
        """docs/RELEASING.md must contain a 'Pre-Tag Checklist' H2 section."""
        assert "## Pre-Tag Checklist" in _content(), (
            "docs/RELEASING.md missing '## Pre-Tag Checklist' section"
        )

    def test_version_bump_procedure_section_exists(self):
        """docs/RELEASING.md must contain a 'Version Bump Procedure' H2 section."""
        assert "## Version Bump Procedure" in _content(), (
            "docs/RELEASING.md missing '## Version Bump Procedure' section"
        )

    def test_tag_push_flow_section_exists(self):
        """docs/RELEASING.md must contain a 'Tag Push Flow' H2 section."""
        assert "## Tag Push Flow" in _content(), (
            "docs/RELEASING.md missing '## Tag Push Flow' section"
        )

    def test_post_publish_verification_section_exists(self):
        """docs/RELEASING.md must contain a 'Post-Publish Verification' H2 section."""
        assert "## Post-Publish Verification" in _content(), (
            "docs/RELEASING.md missing '## Post-Publish Verification' section"
        )

    def test_rollback_procedure_section_exists(self):
        """docs/RELEASING.md must contain a 'Rollback Procedure' H2 section."""
        assert "## Rollback Procedure" in _content(), (
            "docs/RELEASING.md missing '## Rollback Procedure' section"
        )

    def test_version_history_note_section_exists(self):
        """docs/RELEASING.md must contain a 'Version History Note' H2 section."""
        assert "## Version History Note" in _content(), (
            "docs/RELEASING.md missing '## Version History Note' section"
        )


class TestReleasingMdRollbackContent:
    def test_rollback_contains_npm_unpublish(self):
        """Rollback section must document 'npm unpublish' command."""
        assert "npm unpublish" in _content(), (
            "docs/RELEASING.md Rollback section missing 'npm unpublish'"
        )

    def test_rollback_contains_twine_yank(self):
        """Rollback section must document 'twine yank' command."""
        assert "twine yank" in _content(), (
            "docs/RELEASING.md Rollback section missing 'twine yank'"
        )

    def test_rollback_contains_gh_release_delete(self):
        """Rollback section must document 'gh release delete' command."""
        assert "gh release delete" in _content(), (
            "docs/RELEASING.md Rollback section missing 'gh release delete'"
        )

    def test_rollback_contains_git_tag_delete(self):
        """Rollback section must document 'git tag -d' command."""
        assert "git tag -d" in _content(), (
            "docs/RELEASING.md Rollback section missing 'git tag -d'"
        )


class TestReleasingMdPep440Warning:
    def test_version_history_note_warns_about_pep440_shadowing(self):
        """REL-01: Version History Note must warn about PEP 440 pre-release shadowing."""
        content = _content()
        # The warning is present when the note mentions PEP 440 or pre-release ordering
        has_pep440 = "PEP 440" in content
        has_prerelease_warning = re.search(
            r"pre.?release.*shadow|shadow.*pre.?release|higher version|pip.*resolv",
            content,
            re.IGNORECASE,
        ) is not None
        assert has_pep440 or has_prerelease_warning, (
            "docs/RELEASING.md Version History Note does not warn about PEP 440 "
            "pre-release version shadowing"
        )
