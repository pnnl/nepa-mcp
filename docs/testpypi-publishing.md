# Publishing NEPA-MCP to TestPyPI

This guide covers publishing the installable `nepa-mcp` Python distribution to
TestPyPI and testing it with the Codex plugin's non-aggregate MCP layout.

## Before publishing

TestPyPI is publicly accessible. It is a test package index, not a private
registry. Before uploading project code:

1. Confirm public-release approval.
2. Add the approved code license to the repository and package metadata.
3. Add approved author, repository, and project URL metadata.
4. Confirm that the distribution contains no credentials or internal-only files.

TestPyPI package names and versions are global and immutable. If
`nepa-mcp==0.1.0rc1` is uploaded, those files cannot be replaced. Publish a new
release candidate such as `0.1.0rc2` after making changes. If the
`nepa-mcp` distribution name is unavailable, the distribution can use another
name such as `nepa-mcp-toolkit` while retaining the `nepa-mcp` console command.

## Create TestPyPI credentials

1. Register at <https://test.pypi.org/account/register/>.
2. Verify the account email address.
3. Enable two-factor authentication.
4. Create a TestPyPI API token.

Do not place the token in Git, `.env.example`, `pyproject.toml`, MCP config, or
Codex plugin files.

## Build and inspect the package

From the repository root:

```bash
cd /path/to/nepa-mcp-server

uv build
ls -lh dist/
```

Expected artifacts for version `0.1.0rc1`:

```text
dist/nepa_mcp-0.1.0rc1-py3-none-any.whl
dist/nepa_mcp-0.1.0rc1.tar.gz
```

Run the normal verification before publishing:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

## Dry-run the upload

```bash
uv publish \
  --dry-run \
  --publish-url https://test.pypi.org/legacy/ \
  dist/*
```

## Upload to TestPyPI

Read the token without storing it in shell history:

```bash
read -s "TEST_PYPI_TOKEN?TestPyPI token: "
echo
```

Publish both distributions:

```bash
UV_PUBLISH_TOKEN="$TEST_PYPI_TOKEN" uv publish \
  --publish-url https://test.pypi.org/legacy/ \
  --check-url https://test.pypi.org/simple/ \
  dist/*
```

Remove the token from the shell:

```bash
unset TEST_PYPI_TOKEN
```

The project page should be available at:

```text
https://test.pypi.org/project/nepa-mcp/0.1.0rc1/
```

## Test the published package

TestPyPI does not mirror every dependency. Use TestPyPI for `nepa-mcp` and
regular PyPI as the dependency fallback:

```bash
uv venv /tmp/nepa-testpypi

uv pip install \
  --python /tmp/nepa-testpypi/bin/python \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  nepa-mcp==0.1.0rc1

/tmp/nepa-testpypi/bin/nepa-mcp --version
/tmp/nepa-testpypi/bin/nepa-mcp list-servers
/tmp/nepa-testpypi/bin/nepa-mcp doctor
```

## One package install, separate MCP servers

`pipx install nepa-mcp` installs one Python distribution and creates one console
command. It does not install each server separately. The wheel contains all 19
server implementations.

The Codex plugin and generated client configurations then register 19 separate
MCP entries. Each entry starts only its own domain process:

```json
{
  "mcpServers": {
    "gis": {
      "command": "nepa-mcp",
      "args": ["server", "gis"]
    },
    "ipac": {
      "command": "nepa-mcp",
      "args": ["server", "ipac"]
    },
    "cfr": {
      "command": "nepa-mcp",
      "args": ["server", "cfr"]
    }
  }
}
```

The remaining domains follow the same pattern. Tools remain associated with
their individual MCP server names in Codex.

To generate all server entries separately, use the appropriate client command:

```bash
nepa-mcp configure claude
nepa-mcp configure vscode
nepa-mcp configure codex
```

Here, "all" means that the configuration contains every domain as an independent
entry. It does not mean `nepa-mcp server all`.

## Why `server all` is different

One stdio command creates one MCP protocol connection. Therefore:

```bash
nepa-mcp server all
```

is necessarily an aggregate MCP server. It cannot appear to the client as 19
separate MCP connections. This command remains an optional testing convenience
and is not used by the Codex plugin or shipped client configurations.

For the normal non-aggregate setup, install the package once and let the plugin
or `configure` command register the 19 individual `nepa-mcp server <name>`
entries.
