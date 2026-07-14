import asyncio
import sys
import os

# Ensure we're in the chatbot folder or add it to path
sys.path.append(os.path.abspath('.'))

from config import get_settings
from data.loader import CatalogStore
from taxonomy.index_builder import build_indexes
from taxonomy.entity_matcher import configure_matcher
from nlu.mention_extractor import extract_mentions
from nlu.action_classifier import classify as classify_action, _RECOMMEND_MARKER
from nlu.intent import heuristic_intent, _CATALOG_ADVISORY

async def main():
    settings = get_settings()
    catalog = await CatalogStore.create(settings=settings)
    await catalog.load()
    indexes = build_indexes(catalog)
    matcher = configure_matcher(indexes, catalog)
    
    queries = [
        "which is the best online mba program",
        "tell me the best mba courses",
        "are there any best specializations"
    ]
    
    print("Running classification checks...")
    for q in queries:
        mentions = extract_mentions(q, matcher)
        action = classify_action(mentions, q)
        heuristic = heuristic_intent(q)
        print(f"Query: {q}")
        print(f"  Mentions: universities={getattr(mentions, 'universities', None)}, courses={getattr(mentions, 'courses', None)}, specializations={getattr(mentions, 'specializations', None)}")
        print(f"  Classified Action: {action}")
        print(f"  Heuristic Intent: {heuristic}")
        print(f"  Matches _RECOMMEND_MARKER: {bool(_RECOMMEND_MARKER.search(q))}")
        print(f"  Matches _CATALOG_ADVISORY: {bool(_CATALOG_ADVISORY.search(q))}")
        print("-" * 50)

if __name__ == "__main__":
    asyncio.run(main())
