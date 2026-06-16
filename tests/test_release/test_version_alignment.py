"""
Version manifest consistency tests (REL-01, REL-02).

Verifies that all ecosystem version pins are aligned before a release tag is pushed.
"""
import json
import pathlib
import re
import tomllib

REPO_ROOT = pathlib.Path(__file__).parent.parent.parent

PYPROJECT = REPO_ROOT / "pyproject.toml"
CARGO_TOML = REPO_ROOT / "rust" / "Cargo.toml"
NPM_INSTALLER = REPO_ROOT / "npm" / "aba-telemetry-installer" / "package.json"

PLATFORM_PACKAGES = [
    "fwd-darwin-arm64",
    "fwd-darwin-x64",
    "fwd-linux-arm64",
    "fwd-linux-x64",
    "fwd-win32-x64",
]


def _pyproject_version() -> str:
    with open(PYPROJECT, "rb") as fh:
        data = tomllib.load(fh)
    return data["project"]["version"]


def _cargo_version() -> str:
    text = CARGO_TOML.read_text()
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert match, "Could not find version in rust/Cargo.toml"
    return match.group(1)


def _npm_version(path: pathlib.Path) -> str:
    return json.loads(path.read_text())["version"]


class TestVersionAlignment:
    def test_pyproject_toml_version_matches_cargo_toml(self):
        """REL-01: pyproject.toml version must equal rust/Cargo.toml version."""
        py_ver = _pyproject_version()
        cargo_ver = _cargo_version()
        assert py_ver == cargo_ver, (
            f"pyproject.toml version {py_ver!r} != rust/Cargo.toml version {cargo_ver!r}"
        )

    def test_pyproject_toml_version_matches_npm_installer(self):
        """REL-02: pyproject.toml version must equal npm installer package.json version."""
        py_ver = _pyproject_version()
        npm_ver = _npm_version(NPM_INSTALLER)
        assert py_ver == npm_ver, (
            f"pyproject.toml version {py_ver!r} != npm installer version {npm_ver!r}"
        )

    def test_fwd_darwin_arm64_version_matches_pyproject(self):
        """REL-02: npm/fwd-darwin-arm64 version must match pyproject.toml."""
        py_ver = _pyproject_version()
        pkg_ver = _npm_version(REPO_ROOT / "npm" / "fwd-darwin-arm64" / "package.json")
        assert py_ver == pkg_ver, (
            f"pyproject.toml {py_ver!r} != npm/fwd-darwin-arm64 {pkg_ver!r}"
        )

    def test_fwd_darwin_x64_version_matches_pyproject(self):
        """REL-02: npm/fwd-darwin-x64 version must match pyproject.toml."""
        py_ver = _pyproject_version()
        pkg_ver = _npm_version(REPO_ROOT / "npm" / "fwd-darwin-x64" / "package.json")
        assert py_ver == pkg_ver, (
            f"pyproject.toml {py_ver!r} != npm/fwd-darwin-x64 {pkg_ver!r}"
        )

    def test_fwd_linux_arm64_version_matches_pyproject(self):
        """REL-02: npm/fwd-linux-arm64 version must match pyproject.toml."""
        py_ver = _pyproject_version()
        pkg_ver = _npm_version(REPO_ROOT / "npm" / "fwd-linux-arm64" / "package.json")
        assert py_ver == pkg_ver, (
            f"pyproject.toml {py_ver!r} != npm/fwd-linux-arm64 {pkg_ver!r}"
        )

    def test_fwd_linux_x64_version_matches_pyproject(self):
        """REL-02: npm/fwd-linux-x64 version must match pyproject.toml."""
        py_ver = _pyproject_version()
        pkg_ver = _npm_version(REPO_ROOT / "npm" / "fwd-linux-x64" / "package.json")
        assert py_ver == pkg_ver, (
            f"pyproject.toml {py_ver!r} != npm/fwd-linux-x64 {pkg_ver!r}"
        )

    def test_fwd_win32_x64_version_matches_pyproject(self):
        """REL-02: npm/fwd-win32-x64 version must match pyproject.toml."""
        py_ver = _pyproject_version()
        pkg_ver = _npm_version(REPO_ROOT / "npm" / "fwd-win32-x64" / "package.json")
        assert py_ver == pkg_ver, (
            f"pyproject.toml {py_ver!r} != npm/fwd-win32-x64 {pkg_ver!r}"
        )

    def test_all_six_npm_packages_have_identical_versions(self):
        """REL-02: All 6 npm package.json files (installer + 5 platform) must share one version."""
        all_packages = [NPM_INSTALLER] + [
            REPO_ROOT / "npm" / pkg / "package.json" for pkg in PLATFORM_PACKAGES
        ]
        versions = {str(p.parent.name): _npm_version(p) for p in all_packages}
        unique_versions = set(versions.values())
        assert len(unique_versions) == 1, (
            f"npm package versions are not all equal: {versions}"
        )

    def test_version_string_is_semver_format(self):
        """REL-01: Version must match vX.Y.Z tag format (no pre-release suffixes)."""
        ver = _pyproject_version()
        assert re.fullmatch(r"\d+\.\d+\.\d+", ver), (
            f"Version {ver!r} is not a clean X.Y.Z semver string"
        )
