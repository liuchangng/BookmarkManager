"""modules package"""
from .config_manager import ConfigManager
from .secure_store import SecureStore
from .proxy import ProxyManager
from .parser import BookmarkParser
from .bookmark import Bookmark
from .classifier import Classifier, ClassifyRule
from .cache import ClassifyCache
from .fetcher import WebFetcher, FetchResult, FetchCache, ProxyAdapter
from .ai_client import DeepSeekClient, AIResult, AICache, build_classify_prompt, parse_ai_response, test_api_key
from .html_builder import BookmarkHTMLBuilder, build_and_save, validate_html, generate_preview_tree

__all__ = [
    "ConfigManager", "SecureStore", "ProxyManager",
    "BookmarkParser", "Bookmark",
    "Classifier", "ClassifyRule", "ClassifyCache",
    "WebFetcher", "FetchResult", "FetchCache", "ProxyAdapter",
    "DeepSeekClient", "AIResult", "AICache", "test_api_key",
    "BookmarkHTMLBuilder", "build_and_save", "validate_html", "generate_preview_tree",
]
