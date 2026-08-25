# Releasing NEPA MCP

This runbook covers stable production releases to PyPI. PyPI versions and
uploaded files are immutable, so stop if any identity, artifact, or
installation check differs from the intended release.

## One-time production setup

1. Create the GitHub environment `pypi`.
   - Require approval from the project maintainer.
   - Limit deployment tags to `v*`.
   - Do not add a PyPI API token or other publishing secret.
2. On PyPI, configure a pending GitHub Trusted Publisher:
   - PyPI project: `nepa-mcp`
   - GitHub owner: `pnnl`
   - Repository: `nepa-mcp`
   - Workflow: `publish-pypi.yml`
   - Environment: `pypi`
3. Keep the repository's default GitHub Actions token permission at
   `contents: read`.

A pending publisher does not reserve the project name. Configure it close to
the first production upload.

## Prepare a stable release

1. Create a release branch from the current protected `main`.
2. Change the version from the release candidate to the stable version in:
   - `pyproject.toml`
   - `uv.lock`
   - `nepa_mcp/__init__.py`
   - `plugins/nepa-mcp/.codex-plugin/plugin.json`
   - `tests/test_distribution.py`
   - `CITATION.cff`
   - the README citation example, tagged asset URLs, and plugin ref
3. Set the `CITATION.cff` release date.
4. Keep `pipx install nepa-mcp` as the primary README installation route and
   verify that the client and plugin instructions match the release.
5. Pin README package-page assets to the stable tag instead of the mutable
   `main` branch.
6. Regenerate the lockfile:

   ```bash
   uv lock
   ```

7. Run the local release gate:

   ```bash
   uv sync --frozen
   uv run --frozen ruff format --check .
   uv run --frozen ruff check .
   uv run --frozen pytest -q
   uv run --frozen pip-audit --progress-spinner off
   uv build --no-sources
   uvx --from "twine==7.0.0" twine check dist/*
   ```

8. Merge the release pull request only after all required CI checks pass.

## Tag and publish

1. Create an annotated stable tag on the exact merge commit:

   ```bash
   git tag -a v0.1.2 -m "NEPA MCP v0.1.2" <merge-commit>
   git push origin v0.1.2
   ```

2. Dispatch `Publish to PyPI` from that same tag. With the GitHub CLI:

   ```bash
   gh workflow run publish-pypi.yml \
     --ref v0.1.2 \
     -f tag=v0.1.2 \
     -f confirmation=publish
   ```

3. Review the build, test, artifact hashes, and installed-wheel smoke test.
4. Approve the waiting `pypi` environment deployment.
5. Trusted Publishing uploads the exact validated wheel and source
   distribution and creates PyPI attestations.

## Verify before announcing

1. Verify the PyPI project metadata, README rendering, links, license, Python
   requirement, artifact hashes, and attestations.
2. Clean-install the production package on Python 3.12 and 3.14:

   ```bash
   pipx install nepa-mcp==0.1.2
   nepa-mcp --version
   nepa-mcp doctor
   nepa-mcp list-servers
   ```

3. Start all 19 installed servers over MCP stdio and confirm all 46 tools.
4. Run representative GIS and CFR live calls.
5. Publish the matching stable GitHub release.
6. Update the `github-pages` branch to the stable version and production
   `pipx install nepa-mcp` instructions.
7. Verify the deployed Pages site before broader release communication.

If a production artifact is defective, do not reuse or overwrite the version.
Prepare a new patch release. Yank an existing release only when necessary and
record the reason.
