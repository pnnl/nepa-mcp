"""
Repository-health and static-analysis checks.

These encode the non-functional checks from the code-review rubric
(filesystem hygiene, secrets, dependency pinning, README completeness, and
ruff linting) as repeatable pytest cases. Tool-dependent checks (mypy,
pip-audit) are exercised only when those tools are installed, and skip
cleanly otherwise so the suite stays runnable in a minimal environment.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

SERVER_NAMES = [
    "blm",
    "census",
    "cfr",
    "efh",
    "epa_acres",
    "epa_aqs",
    "esa_ranges",
    "fema_nfhl",
    "gbif",
    "gis",
    "ipac",
    "nepa_assist",
    "noaa",
    "nrcs_soils",
    "nrhp",
    "padus",
    "pcsrf",
    "tigerweb_counties",
    "tribal",
    "usace",
]


# ---------------------------------------------------------------------------
# Filesystem hygiene
# ---------------------------------------------------------------------------


class TestFilesystemChecks:
    def test_gitignore_exists_and_excludes_sensitive_paths(self):
        gitignore = ROOT / ".gitignore"
        assert gitignore.exists(), ".gitignore is missing"
        content = gitignore.read_text(encoding="utf-8")
        for pattern in (".env", "__pycache__", ".venv"):
            assert pattern in content, f".gitignore does not exclude {pattern}"

    def test_env_example_exists(self):
        assert (ROOT / ".env.example").exists(), ".env.example template is missing"

    def test_pyproject_and_lockfile_exist(self):
        assert (ROOT / "pyproject.toml").exists()
        assert (ROOT / "uv.lock").exists()

    def test_readme_exists(self):
        assert (ROOT / "README.md").exists()

    def test_public_governance_files_exist(self):
        for filename in (
            "CODE_OF_CONDUCT.md",
            "CONTRIBUTING.md",
            "MAINTAINERS.md",
            "SECURITY.md",
            "SUPPORT.md",
        ):
            assert (ROOT / filename).exists(), f"{filename} is missing"

        contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        conduct = (ROOT / "CODE_OF_CONDUCT.md").read_text(encoding="utf-8")
        security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        assert "Developer Certificate of Origin 1.1" in contributing
        assert 'git commit -s -m "Describe the change"' in contributing
        assert "Contributor Covenant 3.0" in conduct
        assert "policyai@pnnl.gov" in conduct
        assert "PermitAI mailbox" in conduct
        assert "Sarthak Chaturvedi" in conduct
        assert "[NOTE:" not in conduct
        assert "policyai@pnnl.gov" in security
        assert "NEPA MCP Security Report" in security
        assert "PermitAI project mailbox" in security
        assert "Do not report suspected vulnerabilities through a public GitHub issue" in security

    def test_readme_relative_images_exist_and_document_links_are_absolute(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for target in re.findall(r'src="([^"]+)"', readme):
            if target.startswith(("https://", "http://")):
                continue
            assert (ROOT / target).is_file(), f"README image is missing: {target}"

        link_matches = re.findall(r'href="([^"]+)"|\]\(([^)]+)\)', readme)
        relative_links = []
        for html_target, markdown_target in link_matches:
            target = html_target or markdown_target
            if not target.startswith(("https://", "http://", "#", "mailto:")):
                relative_links.append(target)
        assert relative_links == [], f"README contains relative document links: {relative_links}"

    def test_public_release_versions_are_synchronized(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        version = project["version"]
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")

        readme_tag_versions = set(re.findall(r"\bv(\d+\.\d+\.\d+)\b", readme))
        assert readme_tag_versions == {version}
        assert f"version      = {{{version}}}" in readme
        assert re.search(rf"(?m)^version:\s*{re.escape(version)}\s*$", citation)


# ---------------------------------------------------------------------------
# Secrets scan
# ---------------------------------------------------------------------------


class TestNoHardcodedSecrets:
    _SECRET_LITERAL = re.compile(
        r"(API_KEY|SECRET|TOKEN|PASSWORD)\s*=\s*['\"][^'\"]{6,}['\"]",
        re.IGNORECASE,
    )

    def test_no_hardcoded_secret_literals_in_servers(self):
        offenders: list[str] = []
        for name in SERVER_NAMES:
            for py in (ROOT / name).rglob("*.py"):
                if "__pycache__" in py.parts:
                    continue
                for lineno, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
                    if "getenv" in line or "environ" in line or "example" in line.lower():
                        continue
                    if self._SECRET_LITERAL.search(line):
                        offenders.append(f"{py.relative_to(ROOT)}:{lineno}: {line.strip()}")
        assert not offenders, "Hardcoded secret literals found:\n" + "\n".join(offenders)


# ---------------------------------------------------------------------------
# Dependency management
# ---------------------------------------------------------------------------


class TestDependencyHygiene:
    def test_pyproject_declares_dependencies(self):
        content = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        assert "dependencies" in content
        assert "fastmcp" in content

    def test_area_servers_declare_geometry_deps(self):
        # The four ROI-area servers must ship pyproj + shapely in their
        # standalone requirements (equal-area clipping depends on them).
        for name in ("efh", "esa_ranges", "noaa", "nrcs_soils", "pcsrf"):
            req = ROOT / name / "requirements.txt"
            assert req.exists(), f"{name}/requirements.txt missing"
            text = req.read_text(encoding="utf-8")
            assert "pyproj" in text, f"{name} does not declare pyproj"
            assert "shapely" in text, f"{name} does not declare shapely"


# ---------------------------------------------------------------------------
# README completeness
# ---------------------------------------------------------------------------


class TestReadme:
    def test_readme_has_core_sections(self):
        content = (ROOT / "README.md").read_text(encoding="utf-8").lower()
        # Overview/quick-start, install/config, usage, and license-type context.
        assert "quick start" in content or "overview" in content
        assert "configure" in content or "installation" in content or "install" in content
        assert "server" in content  # server inventory / usage
        assert "license" in content


# ---------------------------------------------------------------------------
# Static analysis (tool-gated: skip cleanly if the tool is absent)
# ---------------------------------------------------------------------------


def _tool(name: str) -> str | None:
    return shutil.which(name) or (
        str(Path(sys.prefix) / "bin" / name) if (Path(sys.prefix) / "bin" / name).exists() else None
    )


class TestStaticAnalysis:
    def test_ruff_clean(self):
        ruff = _tool("ruff")
        if ruff is None:
            pytest.skip("ruff not installed")
        proc = subprocess.run([ruff, "check", "."], cwd=ROOT, capture_output=True, text=True)
        assert proc.returncode == 0, f"ruff reported issues:\n{proc.stdout}\n{proc.stderr}"

    def test_mypy_common_clean_ignoring_third_party_stubs(self):
        mypy = _tool("mypy")
        if mypy is None:
            pytest.skip("mypy not installed")
        proc = subprocess.run(
            [mypy, "nepa_mcp_common/", "--ignore-missing-imports"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        # The shared core should be free of real (non-stub) type errors.
        assert proc.returncode == 0, f"mypy found issues in nepa_mcp_common:\n{proc.stdout}"

    def test_pip_audit_no_known_vulnerabilities(self):
        pip_audit = _tool("pip-audit")
        if pip_audit is None:
            pytest.skip("pip-audit not installed")
        proc = subprocess.run(
            [pip_audit, "--progress-spinner", "off"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        combined = proc.stdout + proc.stderr
        assert "No known vulnerabilities found" in combined, f"pip-audit output:\n{combined}"
