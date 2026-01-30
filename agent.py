from __future__ import annotations

import asyncio
import json
import os
import re
import getpass
import hashlib
import html as _html
from html.parser import HTMLParser
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Literal, Callable, cast
from urllib.parse import urlparse

import typer
from openai import OpenAI
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table


console = Console()
app = typer.Typer(add_completion=False, no_args_is_help=True)
config_app = typer.Typer(add_completion=False, help="Manage local config (API keys, defaults).")
app.add_typer(config_app, name="config")

Provider = Literal["openai", "groq"]
SearchMode = Literal["search", "news", "both"]

CONFIG_PATH = Path.home() / ".config" / "web-research-agent" / "config.json"
CONFIG_DIR = CONFIG_PATH.parent


SYSTEM_PROMPT = """You are a Web Research Agent.

Goal:
- Produce a high-level, enterprise-focused research brief.

Rules:
- Be neutral and evidence-oriented.
- Do NOT copy text verbatim.
- Clearly separate facts, trends, and uncertainties.
- If you are uncertain about a claim (or recency), say so.
- Prefer concrete, checkable statements over hype.
- If web sources are provided, ground claims in them and add citations like [1], [2].

Return ONLY valid JSON with this schema:
{
  "summary": "string",
  "key_findings": ["string", "..."],
  "trends": ["string", "..."],
  "open_questions": ["string", "..."],
  "limitations": ["string", "..."],
  "sources": [
    {"title": "string", "url": "string", "publisher": "string?", "date": "string?", "snippet": "string?"}
  ]
}
"""


@dataclass(frozen=True)
class ResearchSpec:
    topic: str
    scope: str
    sources: str
    recency_months: int


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_config() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_config(cfg: Dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass


def _mask_secret(value: str) -> str:
    v = value.strip()
    if len(v) <= 8:
        return "*" * len(v)
    return f"{v[:3]}…{v[-3:]}"


def _get_saved_key(key_name: str) -> Optional[str]:
    cfg = _load_config()
    keys = cfg.get("api_keys")
    if isinstance(keys, dict):
        val = keys.get(key_name)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _save_key(key_name: str, value: str) -> None:
    cfg = _load_config()
    keys = cfg.get("api_keys")
    if not isinstance(keys, dict):
        keys = {}
        cfg["api_keys"] = keys
    keys[key_name] = value
    _save_config(cfg)


def _clear_key(key_name: str) -> None:
    cfg = _load_config()
    keys = cfg.get("api_keys")
    if isinstance(keys, dict) and key_name in keys:
        keys.pop(key_name, None)
        _save_config(cfg)


def _resolve_key(
    *,
    env_name: str,
    saved_key_name: str,
    api_key_override: Optional[str],
    non_interactive: bool,
    prompt_label: str,
    allow_save: bool,
) -> str:
    resolved = api_key_override or os.getenv(env_name) or _get_saved_key(saved_key_name)
    if resolved and resolved.strip():
        return resolved.strip()
    if non_interactive:
        raise typer.BadParameter(f"Missing {env_name}. Set env var or configure saved key.")
    entered = getpass.getpass(f"Enter {prompt_label}: ").strip()
    if not entered:
        raise typer.BadParameter(f"Missing {env_name}.")
    if allow_save and Confirm.ask(f"Save {prompt_label} to {CONFIG_PATH} (local file)?", default=True):
        _save_key(saved_key_name, entered)
    return entered


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _domain_from_url(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def _parse_csv_list(values: Optional[List[str]]) -> List[str]:
    if not values:
        return []
    out: List[str] = []
    for v in values:
        if not isinstance(v, str):
            continue
        for part in v.split(","):
            part = part.strip()
            if part:
                out.append(part)
    return out


def _iso_now_local() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _default_run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _is_fresh(iso_ts: Optional[str], ttl_days: int) -> bool:
    if ttl_days <= 0:
        return True
    if not iso_ts:
        return False
    try:
        ts = datetime.fromisoformat(iso_ts)
    except ValueError:
        return False
    delta = datetime.now(ts.tzinfo) - ts
    return delta.total_seconds() <= ttl_days * 86400


def _cache_read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        return None


def _cache_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _cache_path(cache_dir: Path, namespace: str, key: str) -> Path:
    return cache_dir / namespace / f"{key}.json"


def _parse_selection(selection: str, max_index: int) -> List[int]:
    s = selection.strip().lower()
    if not s:
        return []
    if s in {"all", "*"}:
        return list(range(1, max_index + 1))
    out: set[int] = set()
    for chunk in s.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            a, b = chunk.split("-", 1)
            try:
                start = int(a.strip())
                end = int(b.strip())
            except ValueError:
                continue
            if start > end:
                start, end = end, start
            for i in range(start, end + 1):
                if 1 <= i <= max_index:
                    out.add(i)
        else:
            try:
                i = int(chunk)
            except ValueError:
                continue
            if 1 <= i <= max_index:
                out.add(i)
    return sorted(out)


def _parse_recency_months(text: str) -> Optional[int]:
    t = text.strip().lower()
    m = re.search(r"(\\d+)\\s*(?:month|months|mo)\\b", t)
    if m:
        return int(m.group(1))
    if "last 12 months" in t or "past 12 months" in t:
        return 12
    if "last year" in t or "past year" in t:
        return 12
    return None


def read_input(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def parse_input_text(text: str) -> Dict[str, str]:
    data: Dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        data[key] = value
    return data


def spec_from_input(
    input_text: str,
    topic: Optional[str],
    scope: Optional[str],
    sources: Optional[str],
    recency_months: Optional[int],
    interactive: bool,
) -> ResearchSpec:
    parsed = parse_input_text(input_text)

    parsed_topic = parsed.get("research topic") or parsed.get("topic")
    parsed_scope = parsed.get("scope")
    parsed_sources = parsed.get("sources")
    parsed_recency = _parse_recency_months(parsed.get("recency", "")) if parsed.get("recency") else None

    final_topic = topic or parsed_topic
    final_scope = scope or parsed_scope or "High-level overview"
    final_sources = sources or parsed_sources or "News articles and expert blogs"
    final_recency = recency_months or parsed_recency or 12

    if interactive:
        if not final_topic:
            final_topic = Prompt.ask("Research topic")
        else:
            final_topic = Prompt.ask("Research topic", default=final_topic)
        final_scope = Prompt.ask("Scope", default=final_scope)
        final_sources = Prompt.ask("Source types", default=final_sources)
        final_recency = int(Prompt.ask("Recency (months)", default=str(final_recency)))

    if not final_topic:
        raise typer.BadParameter(
            "Missing research topic. Provide `--topic ...` or set `Research Topic:` in input file."
        )

    if final_recency <= 0:
        raise typer.BadParameter("`recency_months` must be > 0.")

    return ResearchSpec(
        topic=final_topic,
        scope=final_scope,
        sources=final_sources,
        recency_months=final_recency,
    )


def build_user_prompt(spec: ResearchSpec) -> str:
    return (
        f"Research Topic: {spec.topic}\n"
        f"Scope: {spec.scope}\n"
        f"Sources: {spec.sources}\n"
        f"Recency: Last {spec.recency_months} months\n\n"
        "Output guidance:\n"
        "- 1 short paragraph for summary\n"
        "- 6–10 key findings (bullets)\n"
        "- 4–8 trends (bullets)\n"
        "- 4–8 open questions (bullets)\n"
        "- 3–6 limitations/uncertainties (bullets)\n"
        "- If sources are provided, include citations like [1] after claims\n"
    )


def _months_ago_date(months: int) -> str:
    approx_days = int(months * 30.5)
    start = date.today().toordinal() - approx_days
    return date.fromordinal(start).isoformat()


def _serper_post(
    *,
    api_key: str,
    endpoint: str,
    payload: Dict[str, Any],
    cache_dir: Path,
    use_cache: bool,
    cache_ttl_days: int,
) -> Dict[str, Any]:
    import httpx

    cache_key = _sha256_hex(f"serper:{endpoint}:{json.dumps(payload, sort_keys=True)}")
    cache_path = _cache_path(cache_dir, "serper", cache_key)
    if use_cache:
        cached = _cache_read_json(cache_path)
        if isinstance(cached, dict) and _is_fresh(cached.get("cached_at"), cache_ttl_days):
            resp = cached.get("response")
            if isinstance(resp, dict):
                return resp

    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    url = f"https://google.serper.dev/{endpoint.lstrip('/')}"
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        if use_cache:
            _cache_write_json(
                cache_path,
                {
                    "cached_at": _iso_now_local(),
                    "endpoint": endpoint,
                    "payload": payload,
                    "response": data,
                },
            )
        return data


def serper_search(
    *,
    api_key: str,
    query: str,
    mode: SearchMode,
    num: int,
    gl: str,
    hl: str,
    cache_dir: Path,
    use_cache: bool,
    cache_ttl_days: int,
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []

    def add_items(items: Any, kind: str) -> None:
        if not isinstance(items, list):
            return
        for it in items:
            if not isinstance(it, dict):
                continue
            title = it.get("title") or ""
            url = it.get("link") or it.get("url") or ""
            if not isinstance(title, str) or not isinstance(url, str) or not url.strip():
                continue
            publisher_raw = it.get("source") or it.get("publisher")
            date_raw = it.get("date") or it.get("publishedDate")
            snippet_raw = it.get("snippet") or it.get("description")
            results.append(
                {
                    "title": title.strip(),
                    "url": url.strip(),
                    "publisher": publisher_raw.strip() if isinstance(publisher_raw, str) and publisher_raw.strip() else None,
                    "date": date_raw.strip() if isinstance(date_raw, str) and date_raw.strip() else None,
                    "snippet": snippet_raw.strip() if isinstance(snippet_raw, str) and snippet_raw.strip() else None,
                    "_kind": kind,
                }
            )

    if mode in ("search", "both"):
        data = _serper_post(
            api_key=api_key,
            endpoint="search",
            payload={"q": query, "num": num, "gl": gl, "hl": hl},
            cache_dir=cache_dir,
            use_cache=use_cache,
            cache_ttl_days=cache_ttl_days,
        )
        add_items(data.get("organic"), "search")

    if mode in ("news", "both"):
        data = _serper_post(
            api_key=api_key,
            endpoint="news",
            payload={"q": query, "num": num, "gl": gl, "hl": hl},
            cache_dir=cache_dir,
            use_cache=use_cache,
            cache_ttl_days=cache_ttl_days,
        )
        add_items(data.get("news"), "news")

    seen: set[str] = set()
    deduped: List[Dict[str, Any]] = []
    for r in results:
        u = str(r.get("url", "")).strip()
        if not u or u in seen:
            continue
        seen.add(u)
        deduped.append(r)
    return deduped


def build_grounded_prompt(
    spec: ResearchSpec,
    sources: List[Dict[str, Any]],
    *,
    max_total_source_chars: int,
) -> str:
    base = build_user_prompt(spec)
    if not sources:
        return base
    lines: List[str] = [
        base,
        "\nRetrieved sources (use as evidence; cite as [n]):\n"
        "Citation rules:\n"
        "- Append citations like [1] to EVERY key finding and trend.\n"
        "- Avoid long verbatim quotes (max ~20 consecutive words).\n",
        "",
    ]
    used_chars = 0
    for i, s in enumerate(sources, start=1):
        title = s.get("title") or ""
        url = s.get("url") or ""
        publisher = s.get("publisher") or ""
        d = s.get("date") or ""
        header_bits = " — ".join([b for b in [title, publisher, d] if b])
        lines.append(f"[{i}] {header_bits}".strip())
        lines.append(f"URL: {url}")
        snip = s.get("snippet") or ""
        if snip:
            lines.append(f"Snippet: {snip}")
        excerpt = s.get("text_excerpt") or ""
        if isinstance(excerpt, str) and excerpt.strip():
            if used_chars < max_total_source_chars:
                remaining = max_total_source_chars - used_chars
                clipped = excerpt.strip()[:remaining]
                used_chars += len(clipped)
                lines.append("Excerpt:")
                lines.append(clipped)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


class _ExtractionStop(Exception):
    pass


_IGNORED_HTML_TAGS: set[str] = {
    "script",
    "style",
    "noscript",
    "svg",
    "canvas",
    "iframe",
    "form",
    "header",
    "footer",
    "nav",
    "aside",
    "figure",
    "figcaption",
}


class _VisibleTextExtractor(HTMLParser):
    def __init__(self, *, max_chars: int) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: List[str] = []
        self._max_chars = max(1, max_chars)
        self._chars = 0
        self._ignore_depth = 0

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        t = tag.lower()
        if t in _IGNORED_HTML_TAGS:
            self._ignore_depth += 1

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in _IGNORED_HTML_TAGS and self._ignore_depth > 0:
            self._ignore_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._ignore_depth > 0:
            return
        if not data:
            return
        piece = data.strip()
        if not piece:
            return
        remaining = self._max_chars - self._chars
        if remaining <= 0:
            raise _ExtractionStop
        if len(piece) > remaining:
            piece = piece[:remaining]
        self._chunks.append(piece)
        self._chars += len(piece)
        if self._chars >= self._max_chars:
            raise _ExtractionStop

    def text(self) -> str:
        return " ".join(self._chunks)


def _extract_title_from_html(html_text: str) -> Optional[str]:
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", html_text)
    if not m:
        return None
    title = _html.unescape(m.group(1))
    title = re.sub(r"\\s+", " ", title).strip()
    return title or None


def extract_text_from_html(html_text: str, *, max_chars: int) -> str:
    extractor = _VisibleTextExtractor(max_chars=max_chars)
    try:
        extractor.feed(html_text)
    except _ExtractionStop:
        pass
    text = extractor.text()
    text = _html.unescape(text)
    text = re.sub(r"\\s+", " ", text).strip()
    return text[:max_chars]


async def _aiter_bytes_limited(byte_iter: Any, max_bytes: int) -> bytes:
    buf = bytearray()
    read_total = 0
    async for chunk in byte_iter:
        if not chunk:
            continue
        remaining = max_bytes - read_total
        if remaining <= 0:
            break
        if len(chunk) > remaining:
            chunk = chunk[:remaining]
        buf.extend(chunk)
        read_total += len(chunk)
        if read_total >= max_bytes:
            break
    return bytes(buf)


async def _fetch_and_extract_page(
    client: Any,
    url: str,
    *,
    max_bytes: int,
    max_chars_per_page: int,
    timeout_seconds: float,
) -> Dict[str, Any]:
    import httpx

    entry: Dict[str, Any] = {"url": url, "fetched_at": _iso_now_local()}

    async def _work() -> Dict[str, Any]:
        async with client.stream("GET", url) as resp:
            entry["status_code"] = resp.status_code
            ctype = resp.headers.get("content-type") or ""
            entry["content_type"] = ctype
            if resp.status_code >= 400:
                return entry
            raw = await _aiter_bytes_limited(resp.aiter_bytes(), max_bytes)
        html_text = raw.decode("utf-8", errors="ignore")
        page_title = _extract_title_from_html(html_text)
        if page_title:
            entry["page_title"] = page_title

        ctype = str(entry.get("content_type") or "")
        if "text/html" in ctype or "<html" in html_text.lower() or "<body" in html_text.lower():
            text = await asyncio.to_thread(extract_text_from_html, html_text, max_chars=max_chars_per_page)
        else:
            text = ""

        entry["text_len"] = len(text)
        if text:
            entry["text"] = text
        return entry

    try:
        return await asyncio.wait_for(_work(), timeout=timeout_seconds)
    except (asyncio.TimeoutError, TimeoutError):
        entry["error"] = "timeout"
        entry["timed_out"] = True
        return entry
    except httpx.HTTPError as e:
        entry["error"] = str(e)
        return entry
    except Exception as e:
        entry["error"] = str(e)
        return entry


def fetch_pages_and_attach_excerpts(
    *,
    sources: List[Dict[str, Any]],
    max_pages: int,
    max_bytes: int,
    max_chars_per_page: int,
    cache_dir: Path,
    use_cache: bool,
    cache_ttl_days: int,
    user_agent: str,
    timeout_seconds: float,
    concurrency: int,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    import httpx

    fetched: List[Dict[str, Any]] = []
    attempted = 0
    succeeded = 0
    skipped_cached = 0
    timed_out = 0
    errored = 0

    headers = {"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"}
    timeout = httpx.Timeout(timeout_seconds, connect=min(10.0, timeout_seconds))
    page_sources: List[Tuple[Dict[str, Any], str]] = []
    for s in sources[:max_pages]:
        url = str(s.get("url", "")).strip()
        if url:
            page_sources.append((s, url))
    total = len(page_sources)

    async def _run() -> None:
        nonlocal attempted, succeeded, skipped_cached, timed_out, errored
        completed = 0
        sem = asyncio.Semaphore(max(1, concurrency))
        limits = httpx.Limits(
            max_connections=max(1, concurrency) * 2,
            max_keepalive_connections=max(1, concurrency),
        )
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers, limits=limits) as client:

            async def _job(s: Dict[str, Any], url: str, cache_path: Path) -> Tuple[Dict[str, Any], str, Path, Dict[str, Any]]:
                async with sem:
                    entry = await _fetch_and_extract_page(
                        client,
                        url,
                        max_bytes=max_bytes,
                        max_chars_per_page=max_chars_per_page,
                        timeout_seconds=timeout_seconds,
                    )
                return s, url, cache_path, entry

            tasks: List[asyncio.Task[Tuple[Dict[str, Any], str, Path, Dict[str, Any]]]] = []

            for s, url in page_sources:
                attempted += 1
                cache_key = _sha256_hex(f"page:{url}")
                cache_path = _cache_path(cache_dir, "pages", cache_key)
                if use_cache:
                    cached = _cache_read_json(cache_path)
                    if isinstance(cached, dict) and _is_fresh(cached.get("fetched_at"), cache_ttl_days):
                        status_ok = isinstance(cached.get("status_code"), int)
                        if status_ok:
                            text = cached.get("text") if isinstance(cached.get("text"), str) else ""
                            if text:
                                s["text_excerpt"] = text[:max_chars_per_page]
                                succeeded += 1
                            if isinstance(cached.get("page_title"), str) and cached.get("page_title"):
                                s["page_title"] = cached.get("page_title")
                            fetched.append(cached)
                            skipped_cached += 1
                            completed += 1
                            if on_progress:
                                try:
                                    on_progress(completed, total, url)
                                except Exception:
                                    pass
                            continue

                tasks.append(asyncio.create_task(_job(s, url, cache_path)))

            for fut in asyncio.as_completed(tasks):
                s, url, cache_path, entry = await fut
                if isinstance(entry.get("page_title"), str) and entry.get("page_title"):
                    s["page_title"] = entry.get("page_title")
                text = entry.get("text") if isinstance(entry.get("text"), str) else ""
                if text:
                    s["text_excerpt"] = text[:max_chars_per_page]
                    succeeded += 1
                if entry.get("timed_out") is True:
                    timed_out += 1
                elif entry.get("error"):
                    errored += 1
                fetched.append(entry)
                if use_cache:
                    _cache_write_json(cache_path, entry)
                completed += 1
                if on_progress:
                    try:
                        on_progress(completed, total, url)
                    except Exception:
                        pass

    asyncio.run(_run())

    meta = {
        "attempted": attempted,
        "succeeded": succeeded,
        "cached": skipped_cached,
        "timed_out": timed_out,
        "errored": errored,
        "concurrency": concurrency,
        "max_pages": max_pages,
        "max_bytes": max_bytes,
        "max_chars_per_page": max_chars_per_page,
        "user_agent": user_agent,
        "timeout_seconds": timeout_seconds,
    }
    return fetched, meta


def _extract_first_json_object(text: str) -> Optional[str]:
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _coerce_to_list_of_strings(value: Any, field: str) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        out: List[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
            elif item is not None:
                out.append(str(item).strip())
        return [x for x in out if x]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    raise ValueError(f"Field `{field}` must be a list of strings.")


def _coerce_sources(value: Any) -> List[Dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Field `sources` must be a list.")
    out: List[Dict[str, Any]] = []
    for it in value:
        if not isinstance(it, dict):
            continue
        title = it.get("title")
        url = it.get("url")
        if not isinstance(title, str) or not isinstance(url, str) or not url.strip():
            continue
        entry: Dict[str, Any] = {"title": title.strip(), "url": url.strip()}
        for k in ("publisher", "date", "snippet"):
            v = it.get(k)
            if isinstance(v, str) and v.strip():
                entry[k] = v.strip()
        out.append(entry)
    return out


def validate_research_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Output must be a JSON object.")

    summary = payload.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("Field `summary` must be a non-empty string.")

    key_findings = _coerce_to_list_of_strings(payload.get("key_findings"), "key_findings")
    trends = _coerce_to_list_of_strings(payload.get("trends"), "trends")
    open_questions = _coerce_to_list_of_strings(payload.get("open_questions"), "open_questions")
    limitations = _coerce_to_list_of_strings(payload.get("limitations"), "limitations")
    sources = _coerce_sources(payload.get("sources"))

    return {
        "summary": summary.strip(),
        "key_findings": key_findings,
        "trends": trends,
        "open_questions": open_questions,
        "limitations": limitations,
        "sources": sources,
    }


def conduct_research(
    client: Any,
    provider: Provider,
    model: str,
    user_prompt: str,
    temperature: float,
    max_completion_tokens: int,
    top_p: float,
    reasoning_effort: Optional[str],
    stream: bool,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    if provider == "openai":
        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        try:
            kwargs["response_format"] = {"type": "json_object"}
            response = client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content or ""
        except TypeError:
            kwargs.pop("response_format", None)
            response = client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content or ""
    elif provider == "groq":
        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_completion_tokens": max_completion_tokens,
            "top_p": top_p,
            "stream": stream,
        }
        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort

        if stream:
            content_parts: List[str] = []
            completion = client.chat.completions.create(**kwargs)
            for chunk in completion:
                delta = chunk.choices[0].delta.content or ""
                if delta:
                    content_parts.append(delta)
            content = "".join(content_parts)
            response = None
        else:
            response = client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content or ""
    else:
        raise ValueError(f"Unknown provider: {provider}")

    raw_meta: Dict[str, Any] = {
        "model": model,
        "created_at": _utc_now_iso(),
        "provider": provider,
    }
    if response is not None:
        usage = getattr(response, "usage", None)
        if usage is not None:
            raw_meta["usage"] = {
                "input_tokens": getattr(usage, "prompt_tokens", None),
                "output_tokens": getattr(usage, "completion_tokens", None),
                "total_tokens": getattr(usage, "total_tokens", None),
            }

    try:
        parsed = json.loads(content)
        return parsed, raw_meta
    except json.JSONDecodeError:
        extracted = _extract_first_json_object(content)
        if extracted:
            return json.loads(extracted), raw_meta
        raise


def save_outputs(
    output_dir: Path,
    data: Dict[str, Any],
    meta: Dict[str, Any],
    spec: ResearchSpec,
    json_name: str,
    txt_name: str,
) -> Tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / json_name
    txt_path = output_dir / txt_name

    enriched = dict(data)
    enriched["_meta"] = {
        "run_date": str(date.today()),
        "run_timestamp_utc": meta.get("created_at"),
        "provider": meta.get("provider"),
        "model": meta.get("model"),
        "usage": meta.get("usage"),
        "topic": spec.topic,
        "scope": spec.scope,
        "sources": spec.sources,
        "recency_months": spec.recency_months,
        "retrieval": meta.get("retrieval"),
    }

    json_path.write_text(json.dumps(enriched, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    lines: List[str] = []
    lines.append(f"Web Research Summary ({date.today()})")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"Topic: {spec.topic}")
    lines.append(f"Scope: {spec.scope}")
    lines.append(f"Sources: {spec.sources}")
    lines.append(f"Recency: Last {spec.recency_months} months")
    if meta.get("provider"):
        lines.append(f"Provider: {meta.get('provider')}")
    lines.append(f"Model: {meta.get('model')}")
    lines.append("")

    lines.append("Summary:")
    lines.append(data["summary"])
    lines.append("")

    def add_list(title: str, items: List[str]) -> None:
        lines.append(f"{title}:")
        if not items:
            lines.append("- (none)")
        else:
            for item in items:
                lines.append(f"- {item}")
        lines.append("")

    add_list("Key Findings", data["key_findings"])
    add_list("Trends", data["trends"])
    add_list("Open Questions", data["open_questions"])
    add_list("Limitations / Uncertainties", data.get("limitations", []))

    srcs = data.get("sources") or []
    if isinstance(srcs, list) and srcs:
        lines.append("Sources:")
        for i, s in enumerate(srcs, start=1):
            if not isinstance(s, dict):
                continue
            title = s.get("title") or ""
            url = s.get("url") or ""
            publisher = s.get("publisher") or ""
            d = s.get("date") or ""
            bits = " — ".join([b for b in [title, publisher, d] if b])
            lines.append(f"[{i}] {bits}".strip())
            lines.append(f"    {url}")
        lines.append("")

    txt_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return json_path, txt_path


def save_markdown(
    output_dir: Path,
    data: Dict[str, Any],
    meta: Dict[str, Any],
    spec: ResearchSpec,
    md_name: str,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = output_dir / md_name

    def bullets(items: List[str]) -> str:
        if not items:
            return "- (none)\n"
        return "".join(f"- {x}\n" for x in items)

    lines: List[str] = []
    lines.append(f"# Web Research Summary ({date.today()})\n")
    lines.append(f"**Topic:** {spec.topic}\n")
    lines.append(f"**Scope:** {spec.scope}\n")
    lines.append(f"**Recency:** Last {spec.recency_months} months\n")
    if meta.get("provider"):
        lines.append(f"**Provider:** {meta.get('provider')}\n")
    lines.append(f"**Model:** {meta.get('model')}\n")

    lines.append("\n## Summary\n")
    lines.append(data["summary"].strip() + "\n")

    lines.append("\n## Key Findings\n")
    lines.append(bullets(data.get("key_findings", [])))

    lines.append("\n## Trends\n")
    lines.append(bullets(data.get("trends", [])))

    lines.append("\n## Open Questions\n")
    lines.append(bullets(data.get("open_questions", [])))

    lines.append("\n## Limitations / Uncertainties\n")
    lines.append(bullets(data.get("limitations", [])))

    srcs = data.get("sources") or []
    if isinstance(srcs, list) and srcs:
        lines.append("\n## Sources\n")
        for i, s in enumerate(srcs, start=1):
            if not isinstance(s, dict):
                continue
            title = str(s.get("title", "") or "").strip() or "(untitled)"
            url = str(s.get("url", "") or "").strip()
            publisher = str(s.get("publisher", "") or "").strip()
            d = str(s.get("date", "") or "").strip()
            meta_bits = " — ".join([b for b in [publisher, d] if b])
            label = f"[{i}] {title}"
            if meta_bits:
                label += f" ({meta_bits})"
            if url:
                lines.append(f"- {label}: {url}\n")
            else:
                lines.append(f"- {label}\n")

    md_path.write_text("".join(lines).rstrip() + "\n", encoding="utf-8")
    return md_path


def save_html(
    output_dir: Path,
    data: Dict[str, Any],
    meta: Dict[str, Any],
    spec: ResearchSpec,
    html_name: str,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    html_path = output_dir / html_name

    def esc(x: Any) -> str:
        return _html.escape(str(x or ""))

    def ul(items: Any) -> str:
        if not isinstance(items, list) or not items:
            return "<ul><li>(none)</li></ul>"
        return "<ul>" + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul>"

    srcs = data.get("sources") if isinstance(data.get("sources"), list) else []
    src_html = ""
    if srcs:
        rows: List[str] = []
        for i, s in enumerate(srcs, start=1):
            if not isinstance(s, dict):
                continue
            title = esc(s.get("title") or "(untitled)")
            url = str(s.get("url") or "")
            publisher = esc(s.get("publisher") or "")
            d = esc(s.get("date") or "")
            meta_bits = " — ".join([b for b in [publisher, d] if b])
            meta_span = f"<span class='meta'> {meta_bits}</span>" if meta_bits else ""
            if url:
                rows.append(f"<li>[{i}] <a href='{esc(url)}'>{title}</a>{meta_span}</li>")
            else:
                rows.append(f"<li>[{i}] {title}{meta_span}</li>")
        src_html = "<h2>Sources</h2><ul>" + "".join(rows) + "</ul>"

    doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Web Research Summary</title>
  <style>
    body {{ font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial; margin: 40px; line-height: 1.45; color: #111; }}
    .meta {{ color: #555; font-size: 0.95em; }}
    code {{ background: #f5f5f5; padding: 2px 4px; border-radius: 4px; }}
    h1 {{ margin-bottom: 0.2rem; }}
    h2 {{ margin-top: 1.6rem; }}
    .card {{ border: 1px solid #eee; border-radius: 12px; padding: 16px 18px; background: #fff; max-width: 980px; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>Web Research Summary</h1>
    <div class="meta">
      <div><b>Date:</b> {esc(date.today())}</div>
      <div><b>Topic:</b> {esc(spec.topic)}</div>
      <div><b>Scope:</b> {esc(spec.scope)}</div>
      <div><b>Recency:</b> Last {esc(spec.recency_months)} months</div>
      <div><b>Provider:</b> {esc(meta.get("provider"))} &nbsp; <b>Model:</b> {esc(meta.get("model"))}</div>
    </div>

    <h2>Summary</h2>
    <p>{esc(data.get("summary"))}</p>

    <h2>Key Findings</h2>
    {ul(data.get("key_findings"))}

    <h2>Trends</h2>
    {ul(data.get("trends"))}

    <h2>Open Questions</h2>
    {ul(data.get("open_questions"))}

    <h2>Limitations / Uncertainties</h2>
    {ul(data.get("limitations"))}

    {src_html}
  </div>
</body>
</html>
"""
    html_path.write_text(doc, encoding="utf-8")
    return html_path


def save_run_artifacts(
    *,
    output_dir: Path,
    grounded_prompt: str,
    retrieval: Optional[Dict[str, Any]],
    selected_sources: List[Dict[str, Any]],
    fetched_pages: Optional[List[Dict[str, Any]]],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "prompt.txt").write_text(grounded_prompt, encoding="utf-8")
    payload: Dict[str, Any] = {"retrieval": retrieval, "selected_sources": selected_sources}
    if fetched_pages is not None:
        payload["fetched_pages"] = fetched_pages
    (output_dir / "artifacts.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def render_preview(
    spec: ResearchSpec,
    *,
    provider: Provider,
    model: str,
    temperature: float,
    output_dir: Path,
    web_search_enabled: bool,
    search_mode: SearchMode,
    num_results: int,
) -> None:
    table = Table(show_header=False, box=None)
    table.add_row("Topic", spec.topic)
    table.add_row("Scope", spec.scope)
    table.add_row("Sources", spec.sources)
    table.add_row("Recency (months)", str(spec.recency_months))
    table.add_row("Web search", "on" if web_search_enabled else "off")
    if web_search_enabled:
        table.add_row("Search mode", search_mode)
        table.add_row("Results", str(num_results))
    table.add_row("Provider", provider)
    table.add_row("Model", model)
    table.add_row("Temperature", str(temperature))
    table.add_row("Output dir", str(output_dir))
    console.print(Panel(table, title="Run Preview", expand=False))


def filter_sources(
    sources: List[Dict[str, Any]],
    *,
    allow_domains: List[str],
    block_domains: List[str],
) -> List[Dict[str, Any]]:
    def matches(domain: str, pattern: str) -> bool:
        p = pattern.lower().strip()
        if not p:
            return False
        d = domain.lower().strip()
        return d == p or d.endswith("." + p)

    out: List[Dict[str, Any]] = []
    for s in sources:
        url = str(s.get("url", "")).strip()
        domain = _domain_from_url(url)
        if allow_domains and not any(matches(domain, p) for p in allow_domains):
            continue
        if block_domains and any(matches(domain, p) for p in block_domains):
            continue
        out.append(s)
    return out


def render_sources_table(sources: List[Dict[str, Any]], title: str) -> None:
    table = Table(show_header=True, header_style="bold")
    table.add_column("#", style="dim", width=4)
    table.add_column("Kind", style="dim", width=6)
    table.add_column("Domain", style="dim")
    table.add_column("Title")
    table.add_column("Publisher", style="dim")
    table.add_column("Date", style="dim")
    for i, s in enumerate(sources, start=1):
        url = str(s.get("url", "")).strip()
        table.add_row(
            str(i),
            str(s.get("_kind", "") or ""),
            _domain_from_url(url),
            str(s.get("title", "") or "")[:80],
            str(s.get("publisher", "") or "")[:24],
            str(s.get("date", "") or "")[:16],
        )
    console.print(Panel(table, title=title, expand=False))


def pick_sources_interactively(sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not sources:
        return []
    render_sources_table(sources, title="Search Results")
    selection = Prompt.ask("Select sources (e.g. 1-5,8 or all)", default="all")
    indices = _parse_selection(selection, max_index=len(sources))
    if not indices:
        return []
    picked = [sources[i - 1] for i in indices]
    console.print(f"Selected {len(picked)} sources.")
    return picked


@app.command()
def init(
    path: Path = typer.Argument(Path("input.txt"), help="Where to write the input template."),
    force: bool = typer.Option(False, "--force", help="Overwrite if the file already exists."),
) -> None:
    if path.exists() and not force:
        raise typer.BadParameter(f"{path} already exists. Use --force to overwrite.")
    template = (
        "Research Topic: AI agents in enterprise productivity\n"
        "Scope: High-level overview\n"
        "Sources: News articles and expert blogs\n"
        "Recency: Last 12 months\n"
    )
    path.write_text(template, encoding="utf-8")
    console.print(f"Wrote template to {path}")


@app.command()
def run(
    input_file: Path = typer.Option(Path("input.txt"), "--input", help="Input file (key: value lines)."),
    topic: Optional[str] = typer.Option(None, "--topic", help="Override topic."),
    scope: Optional[str] = typer.Option(None, "--scope", help="Override scope."),
    sources: Optional[str] = typer.Option(None, "--sources", help="Override source types."),
    recency_months: Optional[int] = typer.Option(None, "--recency-months", min=1, help="Recency window in months."),
    provider: str = typer.Option("openai", "--provider", help="LLM provider: openai|groq"),
    model: str = typer.Option("gpt-4.1-mini", "--model", help="Model name (provider-specific)."),
    temperature: float = typer.Option(0.35, "--temperature", min=0.0, max=2.0),
    max_completion_tokens: int = typer.Option(4096, "--max-completion-tokens", min=1, help="Max completion tokens (Groq)."),
    top_p: float = typer.Option(1.0, "--top-p", min=0.0, max=1.0, help="Top-p sampling (Groq)."),
    reasoning_effort: Optional[str] = typer.Option(None, "--reasoning-effort", help="Reasoning effort (Groq, if supported)."),
    stream: bool = typer.Option(False, "--stream", help="Stream response (Groq)."),
    api_key: Optional[str] = typer.Option(None, "--api-key", help="API key override (discouraged; prefer env vars)."),
    web_search: bool = typer.Option(
        False, "--web-search/--no-web-search", help="Retrieve sources via Serper before synthesis."
    ),
    serper_api_key: Optional[str] = typer.Option(None, "--serper-api-key", help="Serper key override (discouraged)."),
    search_mode: str = typer.Option("both", "--search-mode", help="Serper search mode: search|news|both"),
    num_results: int = typer.Option(8, "--num-results", min=1, max=20, help="Number of search results to retrieve."),
    gl: str = typer.Option("us", "--gl", help="Serper country (gl)."),
    hl: str = typer.Option("en", "--hl", help="Serper language (hl)."),
    pick_sources: bool = typer.Option(False, "--pick-sources", help="Interactively select which sources to use."),
    allow_domain: Optional[List[str]] = typer.Option(
        None, "--allow-domain", help="Allow only these domains (repeat or comma-separate)."
    ),
    block_domain: Optional[List[str]] = typer.Option(
        None, "--block-domain", help="Exclude these domains (repeat or comma-separate)."
    ),
    fetch_pages: bool = typer.Option(False, "--fetch-pages", help="Fetch each selected URL and extract text."),
    max_pages: int = typer.Option(5, "--max-pages", min=1, max=20, help="Max pages to fetch."),
    max_bytes: int = typer.Option(2_000_000, "--max-bytes", min=10_000, help="Max bytes to download per page."),
    fetch_timeout: float = typer.Option(25.0, "--fetch-timeout", min=5.0, help="Per-page fetch timeout (seconds)."),
    fetch_concurrency: int = typer.Option(5, "--fetch-concurrency", min=1, max=20, help="Concurrent page fetches."),
    max_chars_per_page: int = typer.Option(
        6000, "--max-chars-per-page", min=500, help="Max extracted characters per page (used in prompt)."
    ),
    max_total_source_chars: int = typer.Option(
        30_000, "--max-total-source-chars", min=1000, help="Total excerpt budget across all sources."
    ),
    strict_citations: bool = typer.Option(
        True, "--strict-citations/--no-strict-citations", help="Require [n] citations in findings/trends when sources exist."
    ),
    cache: bool = typer.Option(True, "--cache/--no-cache", help="Cache Serper + page fetches."),
    cache_dir: Path = typer.Option(Path(".cache/web-research-agent"), "--cache-dir", help="Cache directory."),
    cache_ttl_days: int = typer.Option(7, "--cache-ttl-days", min=0, help="Cache TTL in days (0 disables TTL)."),
    save_keys: bool = typer.Option(True, "--save-keys/--no-save-keys", help="Allow saving entered keys to config."),
    run_folder: bool = typer.Option(False, "--run-folder", help="Write outputs under runs/<timestamp>/"),
    runs_dir: str = typer.Option("runs", "--runs-dir", help="Base folder for run outputs (under --output-dir)."),
    run_id: Optional[str] = typer.Option(None, "--run-id", help="Run folder name (default: timestamp)."),
    output_dir: Path = typer.Option(Path("."), "--output-dir", help="Output directory."),
    json_name: str = typer.Option("research.json", "--json-name"),
    txt_name: str = typer.Option("research.txt", "--txt-name"),
    md_name: str = typer.Option("research.md", "--md-name"),
    html_name: str = typer.Option("research.html", "--html-name"),
    write_md: bool = typer.Option(True, "--write-md/--no-write-md", help="Write research.md"),
    write_html: bool = typer.Option(True, "--write-html/--no-write-html", help="Write research.html"),
    non_interactive: bool = typer.Option(False, "--non-interactive", help="Do not prompt; fail on missing values."),
    show_prompt: bool = typer.Option(False, "--show-prompt", help="Print the prompt sent to the model."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview run config; do not call the API."),
) -> None:
    provider = provider.strip().lower()
    if provider not in {"openai", "groq"}:
        raise typer.BadParameter("`--provider` must be one of: openai, groq")
    provider_typed = cast(Provider, provider)

    search_mode = search_mode.strip().lower()
    if search_mode not in {"search", "news", "both"}:
        raise typer.BadParameter("`--search-mode` must be one of: search, news, both")
    search_mode_typed = cast(SearchMode, search_mode)

    key_env = "OPENAI_API_KEY" if provider == "openai" else "GROQ_API_KEY"
    saved_key_name = "openai" if provider == "openai" else "groq"

    if not input_file.exists():
        if non_interactive:
            raise typer.BadParameter(f"Input file not found: {input_file}")
        console.print(f"[yellow]Input file not found:[/] {input_file}")
        if Confirm.ask("Create a template input.txt now?", default=True):
            init(path=input_file, force=False)

    input_text = read_input(input_file) if input_file.exists() else ""
    spec = spec_from_input(
        input_text=input_text,
        topic=topic,
        scope=scope,
        sources=sources,
        recency_months=recency_months,
        interactive=not non_interactive,
    )

    allow_domains = _parse_csv_list(allow_domain)
    block_domains = _parse_csv_list(block_domain)

    final_output_dir = output_dir
    final_run_id = run_id
    if run_folder:
        final_run_id = final_run_id or _default_run_id()
        final_output_dir = output_dir / runs_dir / final_run_id

    render_preview(
        spec,
        provider=provider_typed,
        model=model,
        temperature=temperature,
        output_dir=final_output_dir,
        web_search_enabled=bool(web_search),
        search_mode=search_mode_typed,
        num_results=num_results,
    )
    if show_prompt or (not non_interactive and Confirm.ask("Show the base prompt?", default=False)):
        console.print(Panel(build_user_prompt(spec), title="Base Prompt", expand=False))
    if dry_run:
        console.print("Dry run complete.")
        raise typer.Exit(0)

    if not non_interactive and not Confirm.ask("Run research now (API call)?", default=True):
        raise typer.Exit(0)

    resolved_key = _resolve_key(
        env_name=key_env,
        saved_key_name=saved_key_name,
        api_key_override=api_key,
        non_interactive=non_interactive,
        prompt_label=key_env,
        allow_save=save_keys,
    )

    if provider == "openai":
        client: Any = OpenAI(api_key=resolved_key)
    else:
        from groq import Groq

        client = Groq(api_key=resolved_key)

    retrieved_sources: List[Dict[str, Any]] = []
    selected_sources: List[Dict[str, Any]] = []
    retrieval_meta: Optional[Dict[str, Any]] = None
    fetched_pages: Optional[List[Dict[str, Any]]] = None
    if web_search:
        serper_key = _resolve_key(
            env_name="SERPER_API_KEY",
            saved_key_name="serper",
            api_key_override=serper_api_key,
            non_interactive=non_interactive,
            prompt_label="SERPER_API_KEY",
            allow_save=save_keys,
        )
        start_date = _months_ago_date(spec.recency_months)
        query = f"{spec.topic} after:{start_date}"
        with console.status("Searching the web (Serper)..."):
            retrieved_sources = serper_search(
                api_key=serper_key,
                query=query,
                mode=search_mode_typed,
                num=num_results,
                gl=gl,
                hl=hl,
                cache_dir=cache_dir,
                use_cache=cache,
                cache_ttl_days=cache_ttl_days,
            )
        retrieved_sources = filter_sources(
            retrieved_sources,
            allow_domains=allow_domains,
            block_domains=block_domains,
        )
        selected_sources = list(retrieved_sources)
        if pick_sources and not non_interactive:
            selected_sources = pick_sources_interactively(retrieved_sources)
        else:
            console.print(f"Selected {len(selected_sources)} sources.")
        retrieval_meta = {
            "provider": "serper",
            "mode": search_mode_typed,
            "num_requested": num_results,
            "num_returned": len(retrieved_sources),
            "num_selected": len(selected_sources),
            "query": query,
            "gl": gl,
            "hl": hl,
            "recency_note": "Recency filtering is best-effort via Google query operators.",
            "filters": {"allow_domains": allow_domains, "block_domains": block_domains},
            "cache": {"enabled": cache, "cache_dir": str(cache_dir), "ttl_days": cache_ttl_days},
        }

    if fetch_pages and selected_sources:
        console.print(
            f"Fetching up to {min(max_pages, len(selected_sources))} pages (timeout {fetch_timeout:.0f}s each)..."
        )
        def _progress(i: int, total: int, url: str) -> None:
            domain = _domain_from_url(url)
            status.update(f"Fetching and extracting pages... ({i}/{total}) {domain}")

        with console.status("Fetching and extracting pages...") as status:
            fetched_pages, fetch_meta = fetch_pages_and_attach_excerpts(
                sources=selected_sources,
                max_pages=max_pages,
                max_bytes=max_bytes,
                max_chars_per_page=max_chars_per_page,
                cache_dir=cache_dir,
                use_cache=cache,
                cache_ttl_days=cache_ttl_days,
                user_agent="web-research-agent/1.0 (+https://github.com/openai/codex)",
                timeout_seconds=fetch_timeout,
                concurrency=fetch_concurrency,
                on_progress=_progress,
            )
        if retrieval_meta is None:
            retrieval_meta = {}
        retrieval_meta["fetch"] = fetch_meta

    user_prompt = build_grounded_prompt(
        spec,
        selected_sources if selected_sources else retrieved_sources,
        max_total_source_chars=max_total_source_chars,
    )
    if show_prompt and web_search:
        console.print(Panel(user_prompt, title="Prompt (Grounded)", expand=False))

    with console.status("Researching..."):
        raw, meta = conduct_research(
            client,
            provider=provider_typed,
            model=model,
            user_prompt=user_prompt,
            temperature=temperature,
            max_completion_tokens=max_completion_tokens,
            top_p=top_p,
            reasoning_effort=reasoning_effort,
            stream=stream,
        )

    if retrieval_meta:
        meta["retrieval"] = retrieval_meta

    data = validate_research_payload(raw)
    src_for_output = selected_sources if selected_sources else retrieved_sources
    if src_for_output:
        data["sources"] = [
            {k: v for k, v in s.items() if k in {"title", "url", "publisher", "date", "snippet"} and v}
            for s in src_for_output
        ]

    if src_for_output and strict_citations:
        missing: List[str] = []
        for item in data.get("key_findings", []):
            if isinstance(item, str) and not re.search(r"\[\d+\]", item):
                missing.append(item)
        for item in data.get("trends", []):
            if isinstance(item, str) and not re.search(r"\[\d+\]", item):
                missing.append(item)
        if missing:
            repair_prompt = (
                user_prompt
                + "\n\nRepair task:\n"
                + "- The JSON output below is missing [n] citations in some key_findings/trends.\n"
                + "- Return corrected JSON only (same schema), ensuring EVERY key finding and trend ends with at least one citation like [1].\n"
                + "- Do not invent new sources; cite only the provided source numbers.\n\n"
                + "Previous JSON:\n"
                + json.dumps(data, indent=2, ensure_ascii=False)
            )
            with console.status("Repairing output (citations)..."):
                repaired_raw, _repaired_meta = conduct_research(
                    client,
                    provider=provider_typed,
                    model=model,
                    user_prompt=repair_prompt,
                    temperature=min(0.2, temperature),
                    max_completion_tokens=max_completion_tokens,
                    top_p=top_p,
                    reasoning_effort=reasoning_effort,
                    stream=False,
                )
            meta["repair"] = {"attempted": True, "timestamp_utc": _utc_now_iso(), "model": model}
            data = validate_research_payload(repaired_raw)
            data["sources"] = [
                {k: v for k, v in s.items() if k in {"title", "url", "publisher", "date", "snippet"} and v}
                for s in src_for_output
            ]

            still_missing: List[str] = []
            for item in data.get("key_findings", []):
                if isinstance(item, str) and not re.search(r"\[\d+\]", item):
                    still_missing.append(item)
            for item in data.get("trends", []):
                if isinstance(item, str) and not re.search(r"\[\d+\]", item):
                    still_missing.append(item)
            if still_missing:
                raise typer.BadParameter(
                    "Citations repair failed (still missing [n] citations). Re-run with --no-strict-citations, "
                    "or try a different --model."
                )

    json_path, txt_path = save_outputs(
        output_dir=final_output_dir,
        data=data,
        meta=meta,
        spec=spec,
        json_name=json_name,
        txt_name=txt_name,
    )

    md_path = save_markdown(final_output_dir, data, meta, spec, md_name) if write_md else None
    html_path = save_html(final_output_dir, data, meta, spec, html_name) if write_html else None
    if run_folder:
        save_run_artifacts(
            output_dir=final_output_dir,
            grounded_prompt=user_prompt,
            retrieval=retrieval_meta,
            selected_sources=src_for_output,
            fetched_pages=fetched_pages,
        )

    done_lines = [f"Wrote {json_path}", f"Wrote {txt_path}"]
    if md_path:
        done_lines.append(f"Wrote {md_path}")
    if html_path:
        done_lines.append(f"Wrote {html_path}")
    if run_folder:
        done_lines.append(f"Wrote {final_output_dir / 'artifacts.json'}")
        done_lines.append(f"Wrote {final_output_dir / 'prompt.txt'}")
    console.print(Panel("\n".join(done_lines), title="Done", expand=False))


@app.command()
def validate(
    json_path: Path = typer.Argument(..., help="Path to a `research.json` file."),
) -> None:
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    core = payload
    if isinstance(payload, dict) and "_meta" in payload:
        core = {k: v for k, v in payload.items() if k != "_meta"}
    validated = validate_research_payload(core)
    console.print(Panel("Valid ✅", title="Schema Check", expand=False))
    console.print(f"Summary length: {len(validated['summary'])} chars")
    console.print(f"Key findings: {len(validated['key_findings'])}")
    console.print(f"Trends: {len(validated['trends'])}")
    console.print(f"Open questions: {len(validated['open_questions'])}")
    console.print(f"Limitations: {len(validated.get('limitations', []))}")
    console.print(f"Sources: {len(validated.get('sources', []))}")


@config_app.command("show")
def config_show() -> None:
    cfg = _load_config()
    keys = cfg.get("api_keys") if isinstance(cfg, dict) else None
    table = Table(show_header=True, header_style="bold")
    table.add_column("Key")
    table.add_column("Saved")
    if isinstance(keys, dict) and keys:
        for name in sorted(keys.keys()):
            val = keys.get(name)
            table.add_row(str(name), _mask_secret(val) if isinstance(val, str) else "(invalid)")
    else:
        table.add_row("(none)", "(none)")
    console.print(Panel(table, title=f"Config: {CONFIG_PATH}", expand=False))


@config_app.command("set-serper-key")
def config_set_serper_key() -> None:
    entered = getpass.getpass("Enter SERPER_API_KEY: ").strip()
    if not entered:
        raise typer.BadParameter("Empty key.")
    _save_key("serper", entered)
    console.print("Saved SERPER_API_KEY.")


@config_app.command("clear-serper-key")
def config_clear_serper_key() -> None:
    if Confirm.ask(f"Remove saved Serper key from {CONFIG_PATH}?", default=False):
        _clear_key("serper")
        console.print("Cleared SERPER_API_KEY.")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
