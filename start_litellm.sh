#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Start LiteLLM Proxy for BMAD Agents
# Usage: ./start_litellm.sh
# ─────────────────────────────────────────────────────────────────────────────

set -a
source .env
set +a

echo ""
echo "🚀 Starting LiteLLM Proxy..."
echo "   Config : litellm_config.yaml"
echo "   Port   : 4000"
echo "   Models : groq/llama-3.3-70b, groq/llama-3.1-8b, cerebras/qwen-3, gemini/gemini-pro"
echo "   Key    : bmad-litellm-key-2025"
echo ""
echo "   Test with:"
echo "   curl http://localhost:4000/health"
echo "   curl http://localhost:4000/v1/models -H 'Authorization: Bearer bmad-litellm-key-2025'"
echo ""

litellm --config litellm_config.yaml --port 4000 --detailed_debug
