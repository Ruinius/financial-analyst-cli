# AGENTS.md

Welcome to the `financial-analyst-cli` project.

## Project Structure
- [AGENTS.md](file:///f:/AIML projects/financial-analyst-cli/AGENTS.md): Architectural patterns, module boundaries, and documentation standards.
- [.gitignore](file:///f:/AIML projects/financial-analyst-cli/.gitignore): Ignored files configuration.
- [.pre-commit-config.yaml](file:///f:/AIML projects/financial-analyst-cli/.pre-commit-config.yaml): Git pre-commit hooks configuration (linters, secret prevention checks).
- [Cargo.toml](file:///f:/AIML projects/financial-analyst-cli/Cargo.toml): Cargo configuration for the Rust Core calculation engine.
- [docs/architecture.md](file:///f:/AIML projects/financial-analyst-cli/docs/architecture.md): System architecture, folder structure, and software design decisions.
- [docs/cli_spec.md](file:///f:/AIML projects/financial-analyst-cli/docs/cli_spec.md): CLI command hierarchy, options, parameters, and user experience specification.
- [docs/requirements.md](file:///f:/AIML projects/financial-analyst-cli/docs/requirements.md): Scope of capabilities and product requirements translated from financial-analyst-skills.
- [docs/roadmap.md](file:///f:/AIML projects/financial-analyst-cli/docs/roadmap.md): Six-phase development plan for implementing the Financial Analyst CLI.
- [LICENSE](file:///f:/AIML projects/financial-analyst-cli/LICENSE): MIT License.
- [main.py](file:///f:/AIML projects/financial-analyst-cli/main.py): Application entry point.
- [pyproject.toml](file:///f:/AIML projects/financial-analyst-cli/pyproject.toml): Project metadata and dependencies (managed via `uv`), including Maturin build-backend configuration.
- [README.md](file:///f:/AIML projects/financial-analyst-cli/README.md): Project overview and setup instructions.
- [scripts/](file:///f:/AIML projects/financial-analyst-cli/scripts): Temporary directory containing copied pipeline and calculation scripts.
  - [calculate_calculations.py](file:///f:/AIML projects/financial-analyst-cli/scripts/calculate_calculations.py): Derived financial metrics calculation engine.
  - [calculate_modeling.py](file:///f:/AIML projects/financial-analyst-cli/scripts/calculate_modeling.py): Intrinsic value and WACC valuation engine.
  - [generate_json.py](file:///f:/AIML projects/financial-analyst-cli/scripts/generate_json.py): Model JSON generator.
  - [organize.py](file:///f:/AIML projects/financial-analyst-cli/scripts/organize.py): Processed document organization and unit harmonization.
  - [process_classification.py](file:///f:/AIML projects/financial-analyst-cli/scripts/process_classification.py): PDF classification script.
  - [transform_and_append.py](file:///f:/AIML projects/financial-analyst-cli/scripts/transform_and_append.py): Tiger-Transformer output append logic.
  - [markdown_parser.py](file:///f:/AIML projects/financial-analyst-cli/scripts/markdown_parser.py): Markdown table extraction helpers.
  - [market_data.py](file:///f:/AIML projects/financial-analyst-cli/scripts/market_data.py): Yahoo Finance market data and ticker checker.
  - [simple_frontend_server.py](file:///f:/AIML projects/financial-analyst-cli/scripts/simple_frontend_server.py): Local scenario server and viewer host.
- [src/rust_core/lib.rs](file:///f:/AIML projects/financial-analyst-cli/src/rust_core/lib.rs): Rust module with PyO3 bindings for financial and mathematical calculations.
- [src/resources/dictionary/](file:///f:/AIML projects/financial-analyst-cli/src/resources/dictionary): Central accounting glossary and classification dictionary containing definition markdowns and valuation treatment guidelines.


## Architectural Patterns & Guidelines
- **Tooling**: Always use `uv` for Python-related tasks.
- **Execution**: Run Python scripts/tools using `uv run`.
- **Hybrid Build**: Compile the Rust extension module using `maturin develop` before running Python.
- **Commands**: Preferred pattern is `uv run python <file>.py` or `uv run <command>`.
- **OS/Shell**: Windows with PowerShell (`pwsh`).
