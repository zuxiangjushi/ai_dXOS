import re, json, os

class IntentRouter:
    def __init__(self):
        self.dimension_map = {
            "population": ["人口", "常驻人口", "户籍人口", "人数"],
            "weather": ["天气", "气温", "下雨", "温度", "预报", "冷", "热"],
            "traffic": ["交通", "路况", "入口", "封路", "限行"]
        }
        self.macro_regions = {
            "两湖两广": ["湖北", "湖南", "广东", "广西"],
            "两湖": ["湖北", "湖南"],
            "两广": ["广东", "广西"],
            "云贵川": ["云南", "贵州", "四川"],
            "东北三省": ["黑龙江", "吉林", "辽宁"]
        }

    def route(self, query: str) -> dict:
        result = {"regions": [], "cities": [], "dimensions": [], "prompt_override": ""}
        
        # 1. 提取宏观区域
        for macro, provinces in self.macro_regions.items():
            if macro in query:
                result["regions"].extend(provinces)
                query = query.replace(macro, "")
                
        # 2. 提取维度
        for dim, keywords in self.dimension_map.items():
            if any(kw in query for kw in keywords):
                result["dimensions"].append(dim)
                
        # 3. 提取剩余城市
        clean_q = re.sub(r'各大城市|各个城市|的|情况|状态|以及|和|最近|今天|明天', '', query)
        if clean_q.strip():
            result["cities"].append(clean_q.strip())
            
        # ★ 核心升级：注入专家级思考与排版指令
        format_cmd = (
            "\n【系统强制工作流指令：必须严格遵守】\n"
            "你现在是一位专业的首席数据分析师。用户提出了一个多维度的复合问题（涉及天气、人口等）。\n"
            "你必须按照以下步骤输出，绝不允许跳过：\n\n"
            "步骤 1：拆解用户请求并显式写出。说明你识别的区域和维度。\n"
            "步骤 2：输出真实的天气数据。系统下方为你提供了真实的 API 天气检索结果，请将其整理成漂亮的 Markdown 表格。绝不能编造天气！\n"
            "步骤 3：处理人口数据。系统未提供实时人口，请调用你自身的内部知识库给出近似数据，并在表格中注明“*含模型估算，请以官方为准*”。\n"
            "步骤 4：结构要求。必须使用 Markdown 表格，按省份（如：### 一、湖北省）进行分类排版。\n"
            "步骤 5：总结对比。在表格最后，必须写一段【简要对比小结】，对比各地气温梯度和人口趋势。\n"
        )
        
        result["prompt_override"] = format_cmd
        return result

_router = None
def get_router():
    global _router
    if _router is None: _router = IntentRouter()
    return _router
