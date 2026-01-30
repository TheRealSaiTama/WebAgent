<div align="center">

# Web Research Agent

### AI-Powered Deep Research Synthesis Engine

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)
[![OpenAI](https://img.shields.io/badge/OpenAI-412991?style=for-the-badge&logo=openai&logoColor=white)](https://openai.com/)
[![Groq](https://img.shields.io/badge/Groq-F55036?style=for-the-badge&logo=groq&logoColor=white)](https://groq.com/)

**Transform any research topic into structured, citation-backed intelligence briefs in seconds.**

[Features](#-features) | [Quick Start](#-quick-start) | [Usage](#-usage) | [Architecture](#-architecture) | [Configuration](#%EF%B8%8F-configuration)

---

```
     __        __   _       ____                               _
     \ \      / /__| |__   |  _ \ ___  ___  ___  __ _ _ __ ___| |__
      \ \ /\ / / _ \ '_ \  | |_) / _ \/ __|/ _ \/ _` | '__/ __| '_ \
       \ V  V /  __/ |_) | |  _ <  __/\__ \  __/ (_| | | | (__| | | |
        \_/\_/ \___|_.__/  |_| \_\___||___/\___|\__,_|_|  \___|_| |_|
                             _                    _
                            / \   __ _  ___ _ __ | |_
                           / _ \ / _` |/ _ \ '_ \| __|
                          / ___ \ (_| |  __/ | | | |_
                         /_/   \_\__, |\___|_| |_|\__|
                                 |___/
```

</div>

---

## Overview

**Web Research Agent** is an enterprise-grade CLI tool that combines the power of Large Language Models with real-time web search to produce comprehensive, grounded research briefs. Unlike traditional LLM queries that rely on stale training data, this agent actively retrieves live sources, extracts relevant content, and synthesizes findings with proper academic-style citations.

```
Topic: "AI agents in enterprise productivity"
                    |
                    v
    +-------------------------------+
    |     Web Research Agent        |
    |-------------------------------|
    | 1. Live Search (Serper API)   |
    | 2. Page Fetching & Extraction |
    | 3. LLM Synthesis (GPT/Groq)   |
    | 4. Citation Validation        |
    +-------------------------------+
                    |
                    v
    [JSON] [TXT] [Markdown] [HTML]
         Structured Research Brief
```

---

## Features

### Core Capabilities

| Feature | Description |
|---------|-------------|
| **Multi-Provider LLM Support** | Seamlessly switch between OpenAI GPT-4.1 and Groq (Llama, Mixtral) with a single flag |
| **Real-Time Web Search** | Integrated Google Search via Serper API with news + organic results |
| **Intelligent Page Extraction** | Async HTTP fetching with custom HTML parser for clean text extraction |
| **Citation Enforcement** | Automatic citation repair pass ensures every claim is backed by `[n]` references |
| **Multi-Format Output** | Export to JSON, plain text, Markdown, and styled HTML simultaneously |
| **Intelligent Caching** | SHA256-based deduplication saves API costs and speeds up repeated queries |
| **Domain Filtering** | Allowlist/blocklist controls for source quality management |
| **Interactive & Headless Modes** | Full CLI interactivity or `--non-interactive` for CI/CD pipelines |
| **Secure Key Management** | Keys stored with `0o600` permissions in `~/.config/` |

### Advanced Research Pipeline

```
+------------------------------------------------------------------+
|                    RESEARCH PIPELINE                              |
+------------------------------------------------------------------+
|                                                                   |
|   INPUT         RETRIEVAL         SYNTHESIS        OUTPUT         |
|   -----         ---------         ---------        ------         |
|                                                                   |
|   topic    -->  Serper API   -->  OpenAI/Groq  -->  JSON          |
|   scope         (search+news)     (streaming)       TXT           |
|   recency       Page Fetch        Citation Fix      Markdown      |
|   sources       Text Extract      Schema Valid      HTML          |
|                 Domain Filter                       Artifacts     |
|                 Deduplication                                     |
|                                                                   |
+------------------------------------------------------------------+
```

---

## Quick Start

### Prerequisites

- **Python 3.11+** (3.13 recommended)
- **API Keys**:
  - OpenAI API Key _or_ Groq API Key (for LLM synthesis)
  - Serper API Key (for web search) - [Get one free](https://serper.dev)

### Installation

```bash
# Clone the repository
git clone https://github.com/TheRealSaiTama/WebAgent.git
cd web-research-agent

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt
```

### First Run

```bash
# Initialize input template
python agent.py init

# Run your first research (interactive mode)
python agent.py run --web-search --fetch-pages
```

---

## Usage

### Command Reference

```bash
# Core Commands
python agent.py init [PATH]           # Create input.txt template
python agent.py run [OPTIONS]         # Execute research
python agent.py validate <FILE>       # Validate research.json schema

# Configuration Commands
python agent.py config show           # Display saved API keys
python agent.py config set-serper-key # Save Serper API key
python agent.py config clear-serper-key
```

### Research Workflows

#### 1. Basic Research (No Web Search)

```bash
python agent.py run --topic "Quantum computing applications in finance"
```

#### 2. Web-Grounded Research (Recommended)

```bash
python agent.py run \
  --topic "AI agents in enterprise productivity" \
  --web-search \
  --fetch-pages \
  --num-results 10 \
  --max-pages 8
```

#### 3. Full Research Pipeline with All Features

```bash
python agent.py run \
  --topic "Latest developments in autonomous vehicles" \
  --scope "Technical deep-dive focusing on sensor fusion" \
  --recency-months 6 \
  --web-search \
  --search-mode both \
  --num-results 12 \
  --fetch-pages \
  --max-pages 10 \
  --fetch-concurrency 8 \
  --max-chars-per-page 8000 \
  --strict-citations \
  --provider openai \
  --model gpt-4.1-mini \
  --temperature 0.3 \
  --run-folder \
  --write-md \
  --write-html
```

#### 4. Headless Mode for CI/CD

```bash
export OPENAI_API_KEY="sk-..."
export SERPER_API_KEY="..."

python agent.py run \
  --topic "Market analysis: edge computing 2026" \
  --web-search \
  --fetch-pages \
  --non-interactive \
  --output-dir ./reports
```

### Provider Options

<table>
<tr>
<th>OpenAI</th>
<th>Groq</th>
</tr>
<tr>
<td>

```bash
python agent.py run \
  --provider openai \
  --model gpt-4.1-mini \
  --temperature 0.35 \
  --topic "..."
```

</td>
<td>

```bash
python agent.py run \
  --provider groq \
  --model llama-3.3-70b-versatile \
  --temperature 0.4 \
  --stream \
  --topic "..."
```

</td>
</tr>
</table>

### Domain Filtering

Control source quality with allowlists and blocklists:

```bash
# Only use sources from trusted domains
python agent.py run \
  --web-search \
  --allow-domain techcrunch.com,wired.com,arxiv.org

# Block low-quality or irrelevant domains
python agent.py run \
  --web-search \
  --block-domain pinterest.com,quora.com,reddit.com
```

---

## Output Formats

### JSON Schema

```json
{
  "summary": "High-level executive summary...",
  "key_findings": [
    "Finding with citation [1]",
    "Another finding [2][3]"
  ],
  "trends": [
    "Emerging trend [1]",
    "Market shift [4]"
  ],
  "open_questions": [
    "Unresolved research question?",
    "Future investigation area?"
  ],
  "limitations": [
    "Data recency constraint",
    "Geographic scope limitation"
  ],
  "sources": [
    {
      "title": "Source Title",
      "url": "https://...",
      "publisher": "TechCrunch",
      "date": "2026-01-15",
      "snippet": "Brief excerpt..."
    }
  ],
  "_meta": {
    "run_date": "2026-01-30",
    "provider": "openai",
    "model": "gpt-4.1-mini",
    "usage": {
      "input_tokens": 4521,
      "output_tokens": 1832
    }
  }
}
```

### Output Files

| File | Description |
|------|-------------|
| `research.json` | Complete structured data with metadata |
| `research.txt` | Human-readable plain text format |
| `research.md` | GitHub-flavored Markdown |
| `research.html` | Styled HTML report |
| `prompt.txt` | Full prompt sent to LLM (with `--run-folder`) |
| `artifacts.json` | Retrieval metadata and sources (with `--run-folder`) |

---

## Architecture

### System Design

```
+------------------------------------------------------------------+
|                         WEB RESEARCH AGENT                        |
+------------------------------------------------------------------+
|                                                                   |
|  +-------------------+     +-------------------+                  |
|  |   CLI Interface   |     |   Config Manager  |                  |
|  |   (Typer/Rich)    |     |   (~/.config/)    |                  |
|  +--------+----------+     +--------+----------+                  |
|           |                         |                             |
|           v                         v                             |
|  +--------------------------------------------------+            |
|  |              RESEARCH ORCHESTRATOR               |            |
|  |--------------------------------------------------|            |
|  |  - Input parsing (key:value format)              |            |
|  |  - ResearchSpec dataclass                        |            |
|  |  - Pipeline coordination                         |            |
|  +--------------------------------------------------+            |
|           |                                                       |
|           v                                                       |
|  +-------------------+     +-------------------+                  |
|  |   WEB RETRIEVAL   |     |   LLM SYNTHESIS   |                  |
|  |-------------------|     |-------------------|                  |
|  | - Serper API      |     | - OpenAI Client   |                  |
|  | - Page Fetcher    |     | - Groq Client     |                  |
|  | - HTML Parser     |     | - JSON Mode       |                  |
|  | - Cache Layer     |     | - Streaming       |                  |
|  +-------------------+     +-------------------+                  |
|           |                         |                             |
|           v                         v                             |
|  +--------------------------------------------------+            |
|  |              OUTPUT GENERATORS                   |            |
|  |--------------------------------------------------|            |
|  |  save_outputs() -> JSON, TXT                     |            |
|  |  save_markdown() -> MD                           |            |
|  |  save_html() -> Styled HTML                      |            |
|  |  save_run_artifacts() -> Debug files             |            |
|  +--------------------------------------------------+            |
|                                                                   |
+------------------------------------------------------------------+
```

### Key Components

| Component | Function | Description |
|-----------|----------|-------------|
| **CLI Framework** | `typer.Typer()` | Modern CLI with auto-completion |
| **Console UI** | `rich.Console()` | Panels, tables, spinners, prompts |
| **Research Spec** | `ResearchSpec` dataclass | Immutable research parameters |
| **Web Search** | `serper_search()` | Google Search + News via Serper |
| **Page Fetcher** | `fetch_pages_and_attach_excerpts()` | Async concurrent HTTP with httpx |
| **HTML Parser** | `_VisibleTextExtractor` | Custom HTMLParser for clean text |
| **Cache System** | `_cache_*` functions | SHA256-keyed JSON file cache |
| **LLM Client** | `conduct_research()` | Provider-agnostic completion wrapper |
| **Citation Repair** | Strict citations loop | Auto-fix missing `[n]` references |
| **Output Writers** | `save_*` functions | Multi-format serialization |

### Data Flow

```
Input (topic, scope, recency)
         |
         v
+-------------------+
| Serper API Search |---> Cache Check ---> API Call ---> Deduplicate
+-------------------+
         |
         v
+-------------------+
| Domain Filtering  |---> Allow/Block Lists ---> Select Sources
+-------------------+
         |
         v
+-------------------+
| Page Fetching     |---> Async HTTP ---> HTML Parsing ---> Text Extract
+-------------------+
         |
         v
+-------------------+
| Prompt Building   |---> System Prompt + User Prompt + Source Excerpts
+-------------------+
         |
         v
+-------------------+
| LLM Completion    |---> OpenAI/Groq ---> JSON Parse ---> Validate Schema
+-------------------+
         |
         v
+-------------------+
| Citation Repair   |---> Check [n] refs ---> Repair Pass (if needed)
+-------------------+
         |
         v
+-------------------+
| Output Generation |---> JSON + TXT + MD + HTML
+-------------------+
```

---

## Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | For OpenAI | OpenAI API authentication |
| `GROQ_API_KEY` | For Groq | Groq API authentication |
| `SERPER_API_KEY` | For web search | Google Serper API key |

### Saved Configuration

API keys can be saved locally for convenience:

```bash
# Save Serper key
python agent.py config set-serper-key

# View saved keys (masked)
python agent.py config show

# Config location
~/.config/web-research-agent/config.json
```

### CLI Options Reference

<details>
<summary><b>Research Options</b></summary>

| Option | Default | Description |
|--------|---------|-------------|
| `--topic` | - | Research topic (required) |
| `--scope` | "High-level overview" | Research scope |
| `--sources` | "News articles and expert blogs" | Source types |
| `--recency-months` | 12 | Time window for sources |

</details>

<details>
<summary><b>Provider Options</b></summary>

| Option | Default | Description |
|--------|---------|-------------|
| `--provider` | openai | LLM provider: openai, groq |
| `--model` | gpt-4.1-mini | Model name |
| `--temperature` | 0.35 | Sampling temperature |
| `--max-completion-tokens` | 4096 | Max output tokens (Groq) |
| `--top-p` | 1.0 | Top-p sampling (Groq) |
| `--reasoning-effort` | - | Reasoning effort (Groq) |
| `--stream` | false | Stream response (Groq) |

</details>

<details>
<summary><b>Web Search Options</b></summary>

| Option | Default | Description |
|--------|---------|-------------|
| `--web-search` | false | Enable Serper web search |
| `--search-mode` | both | search, news, or both |
| `--num-results` | 8 | Results per search |
| `--gl` | us | Country code |
| `--hl` | en | Language code |
| `--pick-sources` | false | Interactive source selection |
| `--allow-domain` | - | Allowlist domains |
| `--block-domain` | - | Blocklist domains |

</details>

<details>
<summary><b>Page Fetching Options</b></summary>

| Option | Default | Description |
|--------|---------|-------------|
| `--fetch-pages` | false | Enable page fetching |
| `--max-pages` | 5 | Max pages to fetch |
| `--max-bytes` | 2,000,000 | Max bytes per page |
| `--fetch-timeout` | 25.0 | Timeout per page (seconds) |
| `--fetch-concurrency` | 5 | Parallel fetches |
| `--max-chars-per-page` | 6000 | Max extracted chars per page |
| `--max-total-source-chars` | 30000 | Total excerpt budget |

</details>

<details>
<summary><b>Caching Options</b></summary>

| Option | Default | Description |
|--------|---------|-------------|
| `--cache/--no-cache` | true | Enable caching |
| `--cache-dir` | .cache/web-research-agent | Cache directory |
| `--cache-ttl-days` | 7 | Cache TTL in days |

</details>

<details>
<summary><b>Output Options</b></summary>

| Option | Default | Description |
|--------|---------|-------------|
| `--output-dir` | . | Output directory |
| `--run-folder` | false | Use timestamped subfolder |
| `--runs-dir` | runs | Run folder base name |
| `--json-name` | research.json | JSON filename |
| `--txt-name` | research.txt | TXT filename |
| `--md-name` | research.md | Markdown filename |
| `--html-name` | research.html | HTML filename |
| `--write-md` | true | Write Markdown |
| `--write-html` | true | Write HTML |

</details>

---

## Project Structure

```
web-research-agent/
|
|-- agent.py              # Main application (1658 lines)
|-- requirements.txt      # Python dependencies
|-- input.txt             # Research input template
|-- README.md             # This file
|-- .gitignore            # Git ignore rules
|
|-- .venv/                # Python virtual environment
|-- __pycache__/          # Python bytecode cache
|
|-- .cache/               # Intelligent cache storage
|   +-- web-research-agent/
|       |-- pages/        # Fetched page content (SHA256.json)
|       +-- serper/       # Serper API responses (SHA256.json)
|
+-- runs/                 # Timestamped run outputs
    +-- 20260130_232122/
        |-- research.json
        |-- research.txt
        |-- research.md
        |-- research.html
        |-- prompt.txt
        +-- artifacts.json
```

---

## Performance & Optimization

### Caching Strategy

The agent uses SHA256-based content-addressable caching:

```
Query: "AI agents after:2025-01-01"
         |
         v
    SHA256 Hash
         |
         v
.cache/serper/{hash}.json
         |
    +----+----+
    |         |
  HIT       MISS
    |         |
    v         v
 Return    API Call
 Cached    + Cache
```

### Async Page Fetching

Concurrent page downloads with semaphore-based rate limiting:

```python
# Configuration
--fetch-concurrency 5    # 5 parallel downloads
--fetch-timeout 25       # 25s per page
--max-bytes 2000000      # 2MB limit per page
```

### Token Optimization

```
--max-chars-per-page 6000        # Limit per-source excerpt
--max-total-source-chars 30000   # Total prompt budget
```

---

## Examples

### Example 1: Technology Trend Analysis

```bash
python agent.py run \
  --topic "Edge computing adoption in manufacturing 2025-2026" \
  --scope "Market size, key players, and deployment patterns" \
  --recency-months 12 \
  --web-search \
  --search-mode both \
  --num-results 15 \
  --fetch-pages \
  --max-pages 10 \
  --run-folder
```

### Example 2: Competitive Intelligence

```bash
python agent.py run \
  --topic "OpenAI vs Anthropic enterprise product comparison" \
  --scope "Features, pricing, and market positioning" \
  --web-search \
  --allow-domain techcrunch.com,theverge.com,wired.com,venturebeat.com \
  --fetch-pages \
  --provider groq \
  --model llama-3.3-70b-versatile
```

### Example 3: Academic Research

```bash
python agent.py run \
  --topic "Transformer architecture improvements 2024-2026" \
  --scope "Technical innovations and benchmark results" \
  --sources "ArXiv papers and research blogs" \
  --web-search \
  --allow-domain arxiv.org,openreview.net,huggingface.co \
  --fetch-pages \
  --max-pages 12 \
  --strict-citations
```

---

## Troubleshooting

### Common Issues

<details>
<summary><b>Missing API Key Error</b></summary>

```
Error: Missing OPENAI_API_KEY. Set env var or configure saved key.
```

**Solution:**
```bash
export OPENAI_API_KEY="sk-..."
# or
python agent.py config set-serper-key
```

</details>

<details>
<summary><b>Citation Repair Failed</b></summary>

```
Error: Citations repair failed (still missing [n] citations)
```

**Solution:**
```bash
# Disable strict citations
python agent.py run --no-strict-citations ...

# Or try a different model
python agent.py run --model gpt-4.1 ...
```

</details>

<details>
<summary><b>Page Fetch Timeouts</b></summary>

**Solution:**
```bash
# Increase timeout and reduce concurrency
python agent.py run \
  --fetch-timeout 45 \
  --fetch-concurrency 3 \
  --max-pages 5
```

</details>

---

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| **openai** | >=1.0.0 | OpenAI API client |
| **groq** | >=0.9.0 | Groq API client |
| **httpx** | >=0.23.0 | Async HTTP client |
| **typer** | >=0.12.0 | CLI framework |
| **rich** | >=13.7.0 | Terminal UI |

---

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## Acknowledgments

- [OpenAI](https://openai.com) - GPT-4.1 language models
- [Groq](https://groq.com) - Ultra-fast LLM inference
- [Serper](https://serper.dev) - Google Search API
- [Typer](https://typer.tiangolo.com) - CLI framework
- [Rich](https://rich.readthedocs.io) - Terminal formatting

---

<div align="center">

**Built with AI, for AI-powered research.**

[Report Bug](https://github.com/TheRealSaiTama/WebAgent/issues) | [Request Feature](https://github.com/TheRealSaiTama/WebAgent/issues)

</div>
