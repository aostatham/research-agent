# Research Agent — Claude Code Instructions

## Project layout

```
main.py                   # Thin CLI entry point: parse_args(), main() only
src/
  agent/
    orchestrator.py       # Decompose, research loop, reflect
    synthesiser.py        # Report generation (two modes: full / short)
    tools.py              # Tool definitions + Anthropic/Tavily search routing
  llm/
    base.py               # LLMClient ABC + LLMResponse dataclass
    anthropic_client.py   # Anthropic implementation
    ollama_client.py      # Ollama implementation
    retry.py              # Exponential backoff decorator
    builder.py            # build_client(), build_llms() factory functions
  config/
    settings.py           # Config dataclass + three-layer loader
  output/
    formatter.py          # build_metadata(), convert_to_html(), convert_to_pdf()
    writer.py             # save_report(), update_index()
    provenance.py         # Phase C stub (not yet implemented)
config.yaml               # Default runtime config (provider, models, search, limits)
tests/                    # Unit tests — one file per source module
```

`src/` is on the Python path via `pytest.ini pythonpath = src` and `sys.path.insert` in `main.py`.

## Commands

```bash
# Run unit tests (always use this before committing)
pytest tests/ -m "not integration" -v

# Run integration tests (requires live API keys, costs money)
pytest tests/ -m "integration and not ollama" -v

# Run the agent
python main.py "your topic"
python main.py "your topic" -p ollama -m llama3.1
python main.py "your topic" --search-provider tavily
python main.py "your topic" --orchestration-provider ollama --synthesis-provider anthropic
```

## Test conventions

- Unit tests mock all external clients (`anthropic.Anthropic`, `TavilyClient`, `OllamaClient`)
- Integration tests are marked `@pytest.mark.integration` and excluded from the default run
- Patch at the module where the name is looked up, not where it is defined:
  - `patch("llm.builder.AnthropicClient")` — not `patch("llm.anthropic_client.AnthropicClient")`
  - `patch("output.writer.convert_to_pdf")` — not `patch("output.formatter.convert_to_pdf")`
- 199 unit tests must pass before every commit

## Commit style

- One-line subject, imperative mood, no trailing period
- Body paragraph explaining the why, not the what
- No `Co-Authored-By` lines
- Stage specific files — never `git add -A`

## Code conventions

- No comments unless the WHY is non-obvious
- No Co-Authored-By in commits
- Logic changes and structural changes in separate commits
- Docstrings on all public functions and modules

## Config + environment

- `.env` is gitignored — never commit it
- `ANTHROPIC_API_KEY` and `TAVILY_API_KEY` are env vars only
- `config.yaml` holds runtime defaults; CLI flags override them; neither is secret

## Key architectural notes

- `LLMClient` is the provider abstraction — `AnthropicClient` and `OllamaClient` implement it
- `LLMResponse` is normalised: `type="text"` or `type="tool_call"`
- Search routing is controlled by module-level globals in `tools.py` set via `configure_search()`
- Mixed provider: orchestration and synthesis can use different backends per run
- Agentic loop guards in `orchestrator.py`: repeated query detection, tool-call-string detection, fallback synthesis
- Anthropic web search citations appear on text blocks (not tool_result blocks) — non-obvious behaviour documented in `tools.py`
