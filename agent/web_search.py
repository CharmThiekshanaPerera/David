import logging
import requests
from lxml import html
from duckduckgo_search import DDGS

def search_internet(query: str, max_results: int = 5) -> list[dict]:
    """
    Perform a web search using DuckDuckGo.
    Returns a list of dictionaries containing 'title', 'href', and 'body'.
    """
    try:
        with DDGS() as ddgs:
            results = ddgs.text(query, max_results=max_results, backend="lite")
            if not results:
                # Fallback to html backend if lite fails
                results = ddgs.text(query, max_results=max_results, backend="html")
                if not results:
                    return []
            return list(results)
    except Exception as e:
        logging.error(f"Web search failed: {e}")
        return []

def fetch_page_content(url: str, timeout: int = 10) -> str:
    """
    Fetches the content of a webpage and extracts its visible text.
    Returns the extracted text or an empty string on failure.
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        
        # Parse the HTML content
        tree = html.fromstring(response.content)
        
        # Remove unwanted elements like scripts and styles
        for bad in tree.xpath("//script | //style | //noscript | //header | //footer | //nav"):
            bad.getparent().remove(bad)
            
        # Extract text
        text_content = tree.text_content()
        
        # Clean up whitespace
        lines = (line.strip() for line in text_content.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        clean_text = '\\n'.join(chunk for chunk in chunks if chunk)
        
        return clean_text
    except Exception as e:
        logging.error(f"Failed to fetch page {url}: {e}")
        return ""
