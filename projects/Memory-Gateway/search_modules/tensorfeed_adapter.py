"""TensorFeed AI 资讯适配器（v14.0）
- 安装: pip install langchain-tensorfeed
- 无需 API Key
"""
from typing import Dict, List

class TensorFeedAdapter:
    def is_tensorfeed_query(self, query: str) -> bool:
        if not query:
            return False
        keywords = ["AI模型", "模型发布", "模型评测", "AI基准", "LLM动态", "大模型新闻"]
        return any(kw in query for kw in keywords)

    async def search(self, query: str, limit: int = 10) -> List[Dict]:
        if not self.is_tensorfeed_query(query):
            return []
        print(f"   [tensorfeed] 触发 TensorFeed 特化", flush=True)
        try:
            from langchain_tensorfeed import TensorFeedNewsTool
            tool = TensorFeedNewsTool()
            result = tool.invoke({"query": query, "limit": limit})
            results = []
            for item in (result if isinstance(result, list) else []):
                title = item.get("title", "")
                if not title:
                    continue
                results.append({
                    "title": title,
                    "url": item.get("url", "https://tensorfeed.ai"),
                    "content": f"[TensorFeed] {title}\n{item.get('summary', '')[:200]}",
                    "engine": "tensorfeed",
                    "authority": 0.80,
                })
            print(f"   [tensorfeed] 返回 {len(results)} 条", flush=True)
            return results
        except ImportError:
            print(f"   [tensorfeed] langchain-tensorfeed 未安装，跳过", flush=True)
            return []
        except Exception as e:
            print(f"   [tensorfeed] 失败: {type(e).__name__}: {e}", flush=True)
            return []

_instance = None
def get_tensorfeed() -> TensorFeedAdapter:
    global _instance
    if _instance is None:
        _instance = TensorFeedAdapter()
    return _instance
