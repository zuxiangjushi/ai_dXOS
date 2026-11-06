#!/bin/bash
source .env.g0
export PYTHONPATH=/ai/Memory-Gateway:$PYTHONPATH
# 注意：LiteLLM 会尝试导入 "hooks.memory_hooks"，所以我们需要让 "hooks" 模块指向 adapters/litellm_hooks.py
# 可以创建一个软链接或直接将文件命名为 hooks.py
# 简单方法：复制文件到当前目录并命名为 hooks.py
cp adapters/litellm_hooks.py hooks.py
litellm --config litellm_config.yaml --port 9982 --host 0.0.0.0
