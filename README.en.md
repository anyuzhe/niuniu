# Niuniu AI · Personal A-share Research Assistant

[简体中文](README.md) | **English** | [Documentation index](docs/README.md)

Niuniu turns trading knowledge from multiple sources into versioned hypotheses, deterministic research, daily scans, recorded decisions and paper-trading reviews. Its original technical-factor research engine remains part of Research Lab.

This is a research and simulation system. Live broker connectivity and order submission are not enabled by default. Passing software tests does not demonstrate investment performance or Alpha.

## Start

Python 3.11 or newer is required. Run from the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[desktop]"
quantlab desktop --data-root /path/to/niuniu-data --output ./artifacts
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`. CLI-only installation uses `python -m pip install -e .`; optional extras are `desktop`, `market_data`, `vnpy` and `mcp`, as declared in [pyproject.toml](pyproject.toml).

The two macOS `.command` launchers use the project virtual environment and `/Volumes/Lexar/niuniu-data`. Other machines should pass their own data path explicitly.

## Product structure

Trading Desk provides the daily cockpit, themes, stock dossiers, decisions, strategy intents and paper reviews. AI Team keeps independent opinions separate before synthesis. Trading Knowledge stores sources and Playbooks; Research Lab provides factors, experiments, statistical validation and independent execution accounting. Additional modules cover limit-event/sentiment research, bounded autonomous research, developer worktrees, system health and read-only mobile/broker-shadow views.

When configured, ad-hoc stock questions use Fuyao as the primary quote source, with public-web consensus for cross-validation and fallback. These quotes are not formal MarketSnapshot records, Strict PIT evidence or orders.

## Documentation

Detailed manuals are currently maintained in Chinese. This English overview shares the same entry points rather than duplicating a second, easily outdated technical manual.

| Topic | Document |
|---|---|
| Desktop, installation and workflow | [User guide](docs/guide/user-guide.md) |
| Current implementation and remaining work | [Project status](docs/project/status.md) |
| Data, adjustments and evidence boundaries | [Data and evidence](docs/guide/data-and-evidence.md) |
| MCP, scheduled workflows and operations | [Operations](docs/guide/operations.md) |
| Architecture and source navigation | [Architecture](docs/architecture/overview.md), [code map](docs/development/code-map.md) |
| Development and documentation maintenance | [AGENTS.md](AGENTS.md), [contributing](docs/development/contributing.md) |
| Historical records | [Changelog](docs/project/changelog.md), [archive](docs/archive/README.md) |

Source/package paths, `agent_memory/`, `playbooks/`, `research_skills/` and runtime artifacts remain in place. Historical acceptance reports are dated evidence, not current operating instructions. Never replace structured numerical or timing evidence with Markdown summaries.

## License and provenance

No project-wide open-source license is currently declared. Third-party provenance and licenses remain beside their code: [Chan provenance](src/quantlab/_vendor/chanpy/PROVENANCE.json), [Chan license](src/quantlab/_vendor/chanpy/LICENSE), [Alpha provenance](src/quantlab/factors/ALPHA_PROVENANCE.md), [Alpha license](src/quantlab/factors/ALPHA_LICENSE). Those licenses do not grant rights to the entire repository.
