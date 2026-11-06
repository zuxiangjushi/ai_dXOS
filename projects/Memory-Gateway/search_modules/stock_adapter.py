"""免费股票 API（v13.4） - 腾讯/新浪"""
import re
from typing import Dict, List, Optional

import httpx

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"

# 股票名 → 代码
NAME_MAP = {
    "上证指数": "sh000001", "上证": "sh000001",
    "深证指数": "sz399001", "深证": "sz399001",
    "创业板": "sz399006", "沪深300": "sh000300",
    "茅台": "sh600519", "贵州茅台": "sh600519",
    "平安": "sh601318", "中国平安": "sh601318",
    "宁德时代": "sz300750", "比亚迪": "sz002594",
    "工商银行": "sh601398", "建设银行": "sh601939",
    "中国石油": "sh601857", "中石化": "sh600028",
    "腾讯": "hk00700", "阿里": "hk09988",
}


class StockAdapter:
    def __init__(self):
        self.timeout = 8.0

    def is_stock_query(self, query: str) -> bool:
        if not query:
            return False
        keywords = ["股票", "股价", "股市", "A股", "涨跌", "大盘",
                    "上证", "深证", "创业板", "行情", "多少钱一股",
                    "茅台", "平安", "宁德", "比亚迪"]
        return any(kw in query for kw in keywords)

    def extract_codes(self, query: str) -> List[str]:
        codes = []
        for name, code in NAME_MAP.items():
            if name in query:
                codes.append(code)
        if not codes:
            codes = ["sh000001"]
        return list(dict.fromkeys(codes))  # 去重

    def _parse_tencent(self, raw: str) -> Optional[Dict]:
        """解析 v_sh000001="1~上证指数~000001~3235.99~..." """
        try:
            m = re.search(r'"([^"]+)"', raw)
            if not m:
                return None
            parts = m.group(1).split("~")
            if len(parts) < 6:
                return None
            return {
                "name": parts[1],
                "code": parts[2],
                "price": parts[3],
                "prev_close": parts[4],
                "open": parts[5],
                "change": parts[31] if len(parts) > 31 else "",
                "change_pct": parts[32] if len(parts) > 32 else "",
            }
        except Exception:
            return None

    async def search(self, query: str, limit: int = 5) -> List[Dict]:
        if not self.is_stock_query(query):
            return []

        print(f"   [stock] 触发股票特化", flush=True)
        codes = self.extract_codes(query)
        results = []

        try:
            async with httpx.AsyncClient(timeout=self.timeout, headers={"User-Agent": UA}) as c:
                for code in codes[:3]:
                    try:
                        r = await c.get(f"https://qt.gtimg.cn/q={code}")
                        if r.status_code != 200:
                            continue
                        data = self._parse_tencent(r.text)
                        if not data:
                            continue
                        content = (
                            f"【{data['name']}（{data['code']}）实时行情】\n"
                            f"  当前价：{data['price']}\n"
                            f"  昨收：{data['prev_close']}  今开：{data['open']}\n"
                            f"  涨跌：{data['change']}（{data['change_pct']}%）"
                        )
                        results.append({
                            "title": f"{data['name']}实时行情",
                            "url": f"https://gu.qq.com/{code}",
                            "content": content,
                            "engine": "tencent_stock",
                            "authority": 0.90,
                        })
                    except Exception:
                        continue
        except Exception as e:
            print(f"   [stock] 失败: {type(e).__name__}", flush=True)

        print(f"   [stock] 返回 {len(results)} 条", flush=True)
        return results


_instance = None


def get_stock() -> StockAdapter:
    global _instance
    if _instance is None:
        _instance = StockAdapter()
    return _instance


if __name__ == "__main__":
    import asyncio
    async def main():
        s = get_stock()
        for q in ["上证指数行情", "茅台股价", "比亚迪股票"]:
            print(f"\n=== {q} ===")
            for h in await s.search(q):
                print(h['content'])
    asyncio.run(main())
