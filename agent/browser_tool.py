from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from agent.config import AgentConfig


class PolicyBlockedError(ValueError):
    """Raised when a URL is blocked by the browser policy."""


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str


@dataclass(frozen=True)
class PageContent:
    url: str
    text: str
    char_count: int
    status: str  # "ok" | "blocked" | "error" | "empty"


@dataclass
class BrowserPolicy:
    allowed_domains: list[str] = field(default_factory=list)
    blocked_domains: list[str] = field(default_factory=list)

    # Domains that are always blocked regardless of config
    _HARDCODED_BLOCKLIST: frozenset[str] = field(
        default_factory=lambda: frozenset(), init=False, repr=False, compare=False
    )

    def is_allowed(self, url: str) -> tuple[bool, str]:
        """Return (allowed, reason). Checks policy before any fetch."""
        try:
            hostname = urlparse(url).hostname or ""
        except Exception:
            return False, "invalid URL"

        hostname = hostname.lower()
        if hostname.startswith("www."):
            hostname = hostname[4:]

        for blocked in self.blocked_domains:
            bl = blocked.lower().lstrip("www.")
            if hostname == bl or hostname.endswith(f".{bl}"):
                return False, f"domain {hostname!r} is blocked by policy"

        if self.allowed_domains:
            for allowed in self.allowed_domains:
                al = allowed.lower().lstrip("www.")
                if hostname == al or hostname.endswith(f".{al}"):
                    return True, "ok"
            return False, f"domain {hostname!r} not in allowlist"

        return True, "ok"

    @classmethod
    def load(cls, policy_path: Path) -> "BrowserPolicy":
        if not policy_path.exists():
            return cls()
        try:
            data = json.loads(policy_path.read_text(encoding="utf-8"))
            allowed = [str(d).strip() for d in data.get("allowed_domains", []) if d]
            blocked = [str(d).strip() for d in data.get("blocked_domains", []) if d]
            return cls(allowed_domains=allowed, blocked_domains=blocked)
        except (json.JSONDecodeError, OSError):
            return cls()

    def save(self, policy_path: Path) -> None:
        policy_path.parent.mkdir(parents=True, exist_ok=True)
        policy_path.write_text(
            json.dumps(
                {"allowed_domains": self.allowed_domains, "blocked_domains": self.blocked_domains},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def to_dict(self) -> dict:
        return {
            "allowed_domains": list(self.allowed_domains),
            "blocked_domains": list(self.blocked_domains),
        }


class BrowserTool:
    """Sandboxed browser — the only authorized internet channel for David.

    All internet access routes through here: policy-checked, audit-logged,
    content-capped. Agent code must never call requests/urllib directly.
    """

    MAX_PAGE_CHARS_DEFAULT = 20_000

    def __init__(self, config: AgentConfig) -> None:
        self._config = config
        self._policy_path = config.project_root / "config" / "browser_policy.json"
        self._audit_path = config.logs_dir / "browser_audit.jsonl"
        self._max_page_chars = int(
            os.getenv("BROWSER_MAX_PAGE_CHARS", str(self.MAX_PAGE_CHARS_DEFAULT))
        )
        self._pw = None
        self._browser = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def policy(self) -> BrowserPolicy:
        return BrowserPolicy.load(self._policy_path)

    def block_domain(self, domain: str) -> None:
        """Add a domain to the blocklist and persist."""
        p = self.policy
        cleaned = domain.strip().lower().lstrip("www.")
        if cleaned and cleaned not in p.blocked_domains:
            p.blocked_domains.append(cleaned)
            p.save(self._policy_path)

    def unblock_domain(self, domain: str) -> None:
        """Remove a domain from the blocklist and persist."""
        p = self.policy
        cleaned = domain.strip().lower().lstrip("www.")
        if cleaned in p.blocked_domains:
            p.blocked_domains.remove(cleaned)
            p.save(self._policy_path)

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Search DuckDuckGo and return policy-filtered results."""
        self._audit({"action": "search", "query": query, "max_results": max_results})

        try:
            from duckduckgo_search import DDGS

            with DDGS() as ddgs:
                raw = ddgs.text(query, max_results=max_results, backend="lite") or []
                if not raw:
                    raw = ddgs.text(query, max_results=max_results, backend="html") or []
        except Exception as exc:
            self._audit({"action": "search_error", "query": query, "error": str(exc)[:200]})
            return []

        results: list[SearchResult] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            url = str(item.get("href", "")).strip()
            if not url:
                continue
            allowed, reason = self.policy.is_allowed(url)
            if not allowed:
                self._audit({"action": "search_result_blocked", "url": url, "reason": reason})
                continue
            results.append(
                SearchResult(
                    title=str(item.get("title", "")).strip(),
                    url=url,
                    snippet=str(item.get("body", "")).strip(),
                )
            )

        return results

    def read_page(self, url: str) -> PageContent:
        """Fetch readable text from a URL through the controlled browser."""
        allowed, reason = self.policy.is_allowed(url)
        if not allowed:
            self._audit({"action": "read_page_blocked", "url": url, "reason": reason})
            return PageContent(url=url, text="", char_count=0, status="blocked")

        text = self._fetch_text(url)
        text = text[: self._max_page_chars]

        status = "ok" if text else "error"
        self._audit(
            {"action": "read_page", "url": url, "status": status, "char_count": len(text)}
        )

        return PageContent(url=url, text=text, char_count=len(text), status=status)

    def close(self) -> None:
        """Release the Playwright browser if it was started."""
        try:
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._browser = None
        self._pw = None

    def read_audit_log(self, limit: int = 100) -> list[dict]:
        """Return the most recent audit entries, newest first."""
        if not self._audit_path.exists():
            return []
        try:
            lines = self._audit_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        entries: list[dict] = []
        for line in lines[-limit:]:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return list(reversed(entries))

    # ------------------------------------------------------------------
    # Internal fetching
    # ------------------------------------------------------------------

    def _fetch_text(self, url: str) -> str:
        try:
            return self._fetch_with_playwright(url)
        except Exception:
            pass
        return self._fetch_with_requests(url)

    def _fetch_with_playwright(self, url: str) -> str:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("playwright not installed") from exc

        if self._pw is None:
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=True)

        page = self._browser.new_page(java_script_enabled=False)
        try:
            page.goto(url, timeout=15_000, wait_until="domcontentloaded")
            text = page.inner_text("body")
        finally:
            page.close()

        return _clean_text(text)

    def _fetch_with_requests(self, url: str) -> str:
        import requests

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        try:
            resp = requests.get(url, headers=headers, timeout=(5, 15))
            resp.raise_for_status()
        except Exception:
            return ""

        try:
            from lxml import html as lxml_html

            tree = lxml_html.fromstring(resp.content)
            for bad in tree.xpath("//script|//style|//noscript|//header|//footer|//nav"):
                parent = bad.getparent()
                if parent is not None:
                    parent.remove(bad)
            raw = tree.text_content()
        except Exception:
            raw = resp.text

        return _clean_text(raw)

    # ------------------------------------------------------------------
    # Audit logging
    # ------------------------------------------------------------------

    def _audit(self, entry: dict) -> None:
        record = {"timestamp": datetime.now(tz=timezone.utc).isoformat(), **entry}
        try:
            self._audit_path.parent.mkdir(parents=True, exist_ok=True)
            with self._audit_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
        except OSError:
            pass


def _clean_text(raw: str) -> str:
    lines = []
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped:
            lines.append(stripped)
    return "\n".join(lines)
