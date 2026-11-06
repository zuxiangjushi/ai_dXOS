"""免费汇率 API（v13.5） - exchangerate.host + open.er-api"""
import re
from typing import Dict, List

import httpx

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"

# 货币名 → ISO 代码
CURRENCY_MAP = {
    "美元": "USD", "美金": "USD", "欧元": "EUR", "英镑": "GBP",
    "日元": "JPY", "人民币": "CNY", "港币": "HKD", "澳元": "AUD",
    "加元": "CAD", "新加坡元": "SGD", "韩元": "KRW", "卢布": "RUB",
    "USD": "USD", "EUR": "EUR", "CNY": "CNY", "JPY": "JPY",
}


class CurrencyAdapter:
    def __init__(self):
        self.timeout = 8.0

    def is_currency_query(self, query: str) -> bool:
        if not query:
            return False
        keywords = ["汇率", "兑换", "换汇", "多少人民币", "兑人民币",
                    "美元", "欧元", "日元", "汇率多少"]
        return any(kw in query for kw in keywords)

    def extract_currencies(self, query: str) -> List[str]:
        found = []
        for name, code in CURRENCY_MAP.items():
            if name in query:
                found.append(code)
        return list(dict.fromkeys(found))

    async def _fetch_erapi(self, base: str = "USD") -> Dict:
        """open.er-api.com 免费"""
        try:
            async with httpx.AsyncClient(timeout=self.timeout, headers={"User-Agent": UA}) as c:
                r = await c.get(f"https://open.er-api.com/v6/latest/{base}")
                if r.status_code != 200:
                    return {}
                return r.json()
        except Exception:
            return {}

    async def search(self, query: str, limit: int = 5) -> List[Dict]:
        if not self.is_currency_query(query):
            return []

        print(f"   [currency] 触发汇率特化", flush=True)
        currencies = self.extract_currencies(query)
        if not currencies:
            currencies = ["USD"]

        # 用第一个货币做基准
        base = currencies[0]
        data = await self._fetch_erapi(base)
        if not data or data.get("result") != "success":
            print(f"   [currency] API 失败", flush=True)
            return []

        rates = data.get("rates", {})
        results = []

        if len(currencies) >= 2:
            # 两个货币之间的汇率
            target = currencies[1]
            if target in rates:
                rate = rates[target]
                results.append({
                    "title": f"1 {base} = {rate:.4f} {target}",
                    "url": f"https://www.google.com/search?q=1+{base}+to+{target}",
                    "content": f"【实时汇率】1 {base} = {rate:.4f} {target}（数据源: open.er-api.com，更新时间: {data.get('time_last_update_utc', '?')}）",
                    "engine": "erapi",
                    "authority": 0.85,
                })
        else:
            # 单货币 → 对 CNY/USD/EUR
            for target in ["CNY", "USD", "EUR", "JPY"]:
                if target == base:
                    continue
                if target in rates:
                    rate = rates[target]
                    results.append({
                        "title": f"1 {base} = {rate:.4f} {target}",
                        "url": f"https://www.google.com/search?q=1+{base}+to+{target}",
                        "content": f"【实时汇率】1 {base} = {rate:.4f} {target}",
                        "engine": "erapi",
                        "authority": 0.85,
                    })

        print(f"   [currency] 返回 {len(results)} 条", flush=True)
        return results[:limit]


_instance = None


def get_currency() -> CurrencyAdapter:
    global _instance
    if _instance is None:
        _instance = CurrencyAdapter()
    return _instance


if __name__ == "__main__":
    import asyncio
    async def main():
        c = get_currency()
        for q in ["美元汇率", "欧元兑换人民币"]:
            print(f"\n=== {q} ===")
            for h in await c.search(q):
                print(h['content'])
    asyncio.run(main())
