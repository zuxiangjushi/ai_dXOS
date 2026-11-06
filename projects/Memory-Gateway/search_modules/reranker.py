import aiohttp
import asyncio
import re
from typing import List, Dict, Any

class SearchReranker:
    def __init__(self):
        self.jev_url = "http://127.0.0.1:8021/v1/chat/completions"
        self.jev_model = "Qwen3.5-4B"

    async def jev_filter(self, query: str, hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not hits:
            return hits
        sem = asyncio.Semaphore(3)

        async def check_one(hit):
            async with sem:
                title = hit.get('title', '')
                content = hit.get('content', '')[:300]
                prompt = f"User query: {query}\nSearch result title: {title}\nSearch result snippet: {content}\n\nIs this result relevant to the query? Reply ONLY with JSON: {{\"relevant\": true}} or {{\"relevant\": false}}"
                payload = {
                    "model": self.jev_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 1024
                }
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.post(self.jev_url, json=payload, timeout=12) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                text = data['choices'][0]['message']['content']
                                if re.search(r'"relevant"\s*:\s*true', text, re.IGNORECASE):
                                    return hit
                                elif re.search(r'"relevant"\s*:\s*false', text, re.IGNORECASE):
                                    return None
                                return hit
                            return hit
                except Exception:
                    return hit
                    
        results = await asyncio.gather(*(check_one(h) for h in hits))
        kept = [r for r in results if r is not None]
        print(f"   [JEV] Filtered: {len(hits)} -> Kept: {len(kept)}", flush=True)
        return kept

_reranker_instance = None
def get_reranker():
    global _reranker_instance
    if _reranker_instance is None:
        _reranker_instance = SearchReranker()
    return _reranker_instance
