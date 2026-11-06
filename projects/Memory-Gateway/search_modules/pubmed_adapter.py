"""PubMed 医学论文适配器（v14.0）
- 3600万+ 医学论文
- 无需 API Key（3 req/s）
"""
import xml.etree.ElementTree as ET
import httpx
from typing import Dict, List

class PubMedAdapter:
    def __init__(self):
        self.base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
        self.timeout = 10.0
        self.ua = "Memory-Gateway/1.0"

    def is_pubmed_query(self, query: str) -> bool:
        if not query:
            return False
        keywords = ["医学论文", "PubMed", "医学文献", "临床试验", "生物医学", "医学研究"]
        return any(kw in query for kw in keywords)

    async def search(self, query: str, limit: int = 5) -> List[Dict]:
        if not self.is_pubmed_query(query):
            return []
        print(f"   [pubmed] 触发 PubMed 特化", flush=True)
        try:
            async with httpx.AsyncClient(timeout=self.timeout, headers={"User-Agent": self.ua}) as c:
                # 1. 搜索
                r1 = await c.get(f"{self.base}/esearch.fcgi", params={"db": "pubmed", "term": query, "retmax": limit, "retmode": "json"})
                if r1.status_code != 200:
                    return []
                ids = r1.json().get("esearchresult", {}).get("idlist", [])
                if not ids:
                    return []
                # 2. 获取摘要
                r2 = await c.get(f"{self.base}/efetch.fcgi", params={"db": "pubmed", "id": ",".join(ids), "retmode": "xml"})
                if r2.status_code != 200:
                    return []
                root = ET.fromstring(r2.text)
                results = []
                for article in root.findall(".//PubmedArticle")[:limit]:
                    title = article.findtext(".//ArticleTitle", "无标题")
                    abstract = article.findtext(".//AbstractText", "无摘要")
                    pmid = article.findtext(".//PMID", "")
                    results.append({
                        "title": f"[PubMed] {title[:100]}",
                        "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                        "content": f"[PubMed] {title}\n摘要: {abstract[:300]}",
                        "engine": "pubmed",
                        "authority": 0.90,
                    })
                print(f"   [pubmed] 返回 {len(results)} 条", flush=True)
                return results
        except Exception as e:
            print(f"   [pubmed] 失败: {type(e).__name__}: {e}", flush=True)
            return []

_instance = None
def get_pubmed() -> PubMedAdapter:
    global _instance
    if _instance is None:
        _instance = PubMedAdapter()
    return _instance
