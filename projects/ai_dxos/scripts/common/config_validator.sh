#!/bin/bash
# /ai/ai_dxos/scripts/common/config_validator.sh
# 配置验证 + Gateway 配置原子生成

set -euo pipefail
source /ai/ai_dxos/configs/paths.conf

generate_gateway_config() {
    local tmp_file="${GATEWAY_CONFIG}.tmp"
    local bak_file="${GATEWAY_CONFIG}.bak"

    cat > "$tmp_file" <<'YAMLHEADER'
model_list:
YAMLHEADER

    while IFS='|' read -r api_name container_name physical_model port gpu_ids engine pool; do
        [[ "$api_name" =~ ^#.*$ ]] && continue
        [[ -z "$api_name" ]] && continue

        source "$KEYS_CONF_FILE" 2>/dev/null || true
        key_var="KEY_${api_name}"
        api_key="${!key_var:-sk-dummy}"

        cat >> "$tmp_file" <<YAMLITEM
  - model_name: $api_name
    litellm_params:
      model: openai/$api_name
      api_base: http://192.168.10.132:$port
      api_key: $api_key
      custom_llm_provider: openai
    model_info:
      mode: chat
      supports_function_calling: true
YAMLITEM
    done < "$MODELS_CONF_FILE"

    if ! python3 -c "import yaml; yaml.safe_load(open('$tmp_file'))" 2>/dev/null; then
        echo "[ERROR] 生成的 Gateway 配置 YAML 格式无效"
        rm -f "$tmp_file"
        return 1
    fi

    local count=$(grep -c "model_name:" "$tmp_file" || echo "0")
    local expected=$(grep -v "^#" "$MODELS_CONF_FILE" | grep -c "|" || echo "0")
    if [ "$count" -eq 0 ] || [ "$count" -ne "$expected" ]; then
        echo "[ERROR] 模型数量不匹配: 生成 $count, 预期 $expected"
        rm -f "$tmp_file"
        return 1
    fi

    if [ -f "$GATEWAY_CONFIG" ]; then
        cp "$GATEWAY_CONFIG" "$bak_file"
    fi

    sync "$tmp_file" 2>/dev/null || true
    mv "$tmp_file" "$GATEWAY_CONFIG"
    sync "$(dirname "$GATEWAY_CONFIG")" 2>/dev/null || true

    echo "[INFO] Gateway 配置原子发布完成"
    return 0
}

case "${1:-}" in
    --generate-gateway-config)
        generate_gateway_config
        ;;
    *)
        echo "用法: $0 --generate-gateway-config"
        exit 1
        ;;
esac
