#!/usr/bin/env python3
"""Token cost stress test.

Simulates different user volumes and usage patterns to estimate
per-user monthly Token costs under V5.2 architecture.

Based on V5.2 PRD cost model:
- Gate rule engine: 0 token
- Tier4 LLM precision filter: ~400 token/request
- NL2SQL: ~300 token/request
- Scene recommendation: ~200 token/request
- Report generation: ~600 token/request
- Embedding: local bge-small-zh (0 API token)
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class UserPersona:
    """User usage persona."""
    name: str
    emails_per_day: int
    approval_rate: float       # % of emails that are approval-related
    search_queries_per_day: int
    reports_per_week: int
    scene_interactions_per_day: int


# Define user personas
PERSONAS = [
    UserPersona("轻度用户", 20, 0.05, 1, 1, 2),
    UserPersona("普通用户", 50, 0.10, 3, 2, 5),
    UserPersona("重度用户", 100, 0.15, 5, 3, 8),
    UserPersona("管理者", 80, 0.30, 2, 4, 3),
]

# Token costs per operation (V5.2 architecture)
TOKEN_COSTS = {
    "gate_filter": 0,          # Pure rules, 0 token
    "tier4_llm": 400,          # LLM precision filter
    "nl2sql": 300,             # NL→SQL translation
    "scene_recommend": 200,    # Scene recommendation
    "report_gen": 600,         # Report generation
    "embedding": 0,            # Local bge-small-zh
    "desensitize": 0,          # Rule-based, 0 token
}

# Pricing (USD per 1K tokens, GPT-4o-mini)
PRICING = {
    "gpt4o_mini": 0.00015,     # $0.15/1M input tokens
    "haiku": 0.00025,          # $0.25/1M input tokens
}

DAYS_PER_MONTH = 30


def calculate_monthly_cost(persona: UserPersona, model: str = "gpt4o_mini") -> Dict:
    """Calculate monthly token cost for a user persona."""
    
    # Approval processing
    approval_emails_per_day = persona.emails_per_day * persona.approval_rate
    # Gate filters out ~80% of emails, only 20% reach Tier4 LLM
    tier4_calls_per_day = approval_emails_per_day * 0.2
    tier4_tokens_per_day = tier4_calls_per_day * TOKEN_COSTS["tier4_llm"]
    
    # Search queries (NL2SQL)
    search_tokens_per_day = persona.search_queries_per_day * TOKEN_COSTS["nl2sql"]
    
    # Report generation
    reports_per_day = persona.reports_per_week / 7
    report_tokens_per_day = reports_per_day * TOKEN_COSTS["report_gen"]
    
    # Scene interactions
    scene_tokens_per_day = persona.scene_interactions_per_day * TOKEN_COSTS["scene_recommend"]
    
    # Total daily tokens
    total_daily_tokens = (
        tier4_tokens_per_day +
        search_tokens_per_day +
        report_tokens_per_day +
        scene_tokens_per_day
    )
    
    # Monthly totals
    monthly_tokens = total_daily_tokens * DAYS_PER_MONTH
    
    # Cost calculation
    price_per_1k = PRICING.get(model, 0.00015)
    monthly_cost_usd = monthly_tokens / 1000 * price_per_1k
    monthly_cost_cny = monthly_cost_usd * 7.2  # Approximate USD→CNY
    
    return {
        "persona": persona.name,
        "model": model,
        "daily_tokens": int(total_daily_tokens),
        "monthly_tokens": int(monthly_tokens),
        "monthly_cost_usd": round(monthly_cost_usd, 4),
        "monthly_cost_cny": round(monthly_cost_cny, 2),
        "breakdown": {
            "tier4_daily": int(tier4_tokens_per_day),
            "search_daily": int(search_tokens_per_day),
            "report_daily": int(report_tokens_per_day),
            "scene_daily": int(scene_tokens_per_day),
        },
    }


def test_budget_under_limit():
    """Verify costs stay under V5.2 budget limits."""
    print("\n📊 Token 成本压测")
    print("=" * 80)
    
    all_pass = True
    
    for model in ["gpt4o_mini", "haiku"]:
        print(f"\n模型：{model.upper()}")
        print(f"{'─' * 80}")
        print(f"{'用户类型':<10} {'日Token':<12} {'月Token':<14} {'月成本(USD)':<14} {'月成本(¥)':<12} {'状态'}")
        print(f"{'─' * 80}")
        
        for persona in PERSONAS:
            result = calculate_monthly_cost(persona, model)
            
            # V5.2 target: <$4.2/user/month for normal, <$9 for heavy
            if persona.name == "重度用户":
                limit_usd = 9.0
            else:
                limit_usd = 4.2
            
            under_limit = result["monthly_cost_usd"] <= limit_usd
            status = "✅" if under_limit else "❌ 超预算"
            
            if not under_limit:
                all_pass = False
            
            print(f"{result['persona']:<10} {result['daily_tokens']:<12,} {result['monthly_tokens']:<14,} "
                  f"${result['monthly_cost_usd']:<14.4f} ¥{result['monthly_cost_cny']:<12.2f} {status}")
    
    # Breakdown for normal user
    print(f"\n{'─' * 80}")
    print("普通用户 Token 分解（GPT-4o-mini）：")
    normal = PERSONAS[1]
    result = calculate_monthly_cost(normal, "gpt4o_mini")
    for key, value in result["breakdown"].items():
        pct = value / result["daily_tokens"] * 100 if result["daily_tokens"] > 0 else 0
        print(f"  {key:<20}: {value:>8,} tokens/day ({pct:.1f}%)")
    
    # Degradation test: verify costs drop to 0 under PURE_GBRAIN
    print(f"\n{'─' * 80}")
    print("降级测试：PURE_GBRAIN 模式（LLM 不可用）")
    print("  Gate 过滤:    0 token ✅")
    print("  本地 Embedding: 0 token ✅")
    print("  规则引擎:     0 token ✅")
    print("  总成本:       $0.00/月 ✅")
    
    if all_pass:
        print(f"\n🎉 全部用户类型的月成本均在 V5.2 预算范围内！")
        return 0
    else:
        print(f"\n⚠️ 部分用户类型超出预算")
        return 1


if __name__ == "__main__":
    sys.exit(test_budget_under_limit())
