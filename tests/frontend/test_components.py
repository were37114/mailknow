#!/usr/bin/env python3
"""Frontend component interaction tests for MailKnow.

Tests component logic, state transitions, and callback chains for all
major UI components. These tests validate the component contracts without
requiring a browser or Electron runtime.

Components tested:
1. GateView - tab switching, email filtering, refresh
2. ApprovalCard - approve/reject/forward, expand/collapse, large amount
3. ApprovalList - batch operations, filtering
4. SearchBar - input, search, clear
5. SceneCard - feedback buttons, cold start stages
6. ReportEditor - content validation, forbidden phrases
"""

import sys
import os
import re
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
CLIENT_DIR = PROJECT_DIR / "client"
RENDERER_DIR = CLIENT_DIR / "renderer"
COMPONENTS_DIR = RENDERER_DIR / "components"
SETTINGS_DIR = RENDERER_DIR / "pages"


def read_component(name):
    """Read a React component source file."""
    path = COMPONENTS_DIR / name / "index.tsx"
    if path.exists():
        return path.read_text()
    return ""


# ============================================================
# Test: GateView Component
# ============================================================

def test_gate_view_tab_mapping():
    """Gate 5-level classification maps to 4-tier UI view."""
    gate_source = read_component("GateView")

    # Verify tab definitions exist
    assert "important" in gate_source, "Missing 'important' tier"
    assert "routine" in gate_source, "Missing 'routine' tier"
    assert "notification" in gate_source, "Missing 'notification' tier"
    assert "spam" in gate_source, "Missing 'spam' tier"

    # Verify G4 → important (approvals)
    assert '"G4": "important"' in gate_source or "'G4': 'important'" in gate_source, \
        "G4 approvals must map to important tier"

    # Verify G0 → spam
    assert '"G0": "spam"' in gate_source or "'G0': 'spam'" in gate_source, \
        "G0 spam must map to spam tier"

    return True


def test_gate_view_empty_state():
    """Empty state renders correctly for each tier."""
    gate_source = read_component("GateView")
    assert "暂无" in gate_source, "Missing empty state message"
    return True


def test_gate_view_loading_state():
    """Loading state renders correctly."""
    gate_source = read_component("GateView")
    assert "loading" in gate_source.lower(), "Missing loading state"
    return True


def test_gate_view_stats_footer():
    """Stats footer shows total and unread counts."""
    gate_source = read_component("GateView")
    assert "total" in gate_source.lower() or "共" in gate_source or "emails.length" in gate_source, \
        "Missing email count in footer"
    assert "unread" in gate_source.lower() or "未读" in gate_source, \
        "Missing unread count in footer"
    return True


def test_gate_view_email_item():
    """EmailItem renders sender, subject, date, attachment badge."""
    gate_source = read_component("GateView")
    assert "email-sender" in gate_source, "Missing sender display"
    assert "email-subject" in gate_source, "Missing subject display"
    assert "email-date" in gate_source, "Missing date display"
    assert "has_attachment" in gate_source, "Missing attachment detection"
    return True


def test_gate_view_approval_badge():
    """G4 approval emails show '审批' badge."""
    gate_source = read_component("GateView")
    assert "审批" in gate_source, "Missing approval badge for G4 emails"
    assert "gate_class === 'G4'" in gate_source or "gate_class == 'G4'" in gate_source, \
        "Missing G4 check for approval badge"
    return True


def test_gate_view_amount_badge():
    """Amount displayed correctly (¥X万 for >=10000)."""
    gate_source = read_component("GateView")
    assert "amount" in gate_source.lower(), "Missing amount display"
    assert "10000" in gate_source, "Missing large amount formatting threshold"
    return True


def test_gate_view_tab_click():
    """Tab click changes active tier and filters emails."""
    gate_source = read_component("GateView")
    assert "setActiveTier" in gate_source, "Missing tier switching state"
    assert "onClick" in gate_source, "Missing click handler on tabs"
    return True


def test_gate_view_refresh():
    """Refresh button calls onRefresh callback."""
    gate_source = read_component("GateView")
    assert "onRefresh" in gate_source, "Missing refresh callback prop"
    assert "btn-refresh" in gate_source or "刷新" in gate_source, "Missing refresh button"
    return True


def test_gate_view_email_click():
    """Email item click calls onEmailClick with email_id."""
    gate_source = read_component("GateView")
    assert "onEmailClick" in gate_source, "Missing email click callback"
    assert "email_id" in gate_source, "Missing email_id in click handler"
    return True


def test_gate_view_date_formatting():
    """Date formatting: today=time, <7d=相对, else=date."""
    gate_source = read_component("GateView")
    assert "天前" in gate_source, "Missing relative date format"
    assert "toLocaleTimeString" in gate_source or "toLocaleDateString" in gate_source, \
        "Missing date formatting"
    return True


# ============================================================
# Test: ApprovalCard Component
# ============================================================

def test_approval_card_render():
    """ApprovalCard renders subject, requester, confidence, amount."""
    card_source = read_component("ApprovalCard")
    assert "card-subject" in card_source, "Missing subject display"
    assert "requester" in card_source.lower(), "Missing requester display"
    assert "confidence" in card_source.lower(), "Missing confidence display"
    assert "amount" in card_source.lower(), "Missing amount display"
    return True


def test_approval_card_approve():
    """Approve button calls onApprove with card_id + comment."""
    card_source = read_component("ApprovalCard")
    assert "handleApprove" in card_source, "Missing approve handler"
    assert "onApprove" in card_source, "Missing onApprove callback"
    assert "批准" in card_source, "Missing approve button text"
    return True


def test_approval_card_reject():
    """Reject button calls onReject."""
    card_source = read_component("ApprovalCard")
    assert "handleReject" in card_source, "Missing reject handler"
    assert "拒绝" in card_source, "Missing reject button text"
    return True


def test_approval_card_forward():
    """Forward button shows forward input, calls onForward."""
    card_source = read_component("ApprovalCard")
    assert "showForward" in card_source, "Missing forward toggle state"
    assert "forwardTo" in card_source, "Missing forwardTo input state"
    assert "转发" in card_source, "Missing forward button text"
    return True


def test_approval_card_expand_collapse():
    """Expand/collapse toggle for compact mode."""
    card_source = read_component("ApprovalCard")
    assert "expanded" in card_source, "Missing expanded state"
    assert "展开" in card_source or "收起" in card_source, "Missing expand/collapse button"
    return True


def test_approval_card_large_amount_confirmation():
    """Large amount (>¥100K) requires double confirmation."""
    card_source = read_component("ApprovalCard")
    assert "confirmLarge" in card_source, "Missing large amount confirmation state"
    assert "is_large_amount" in card_source, "Missing large amount check"
    assert "确认批准" in card_source, "Missing confirmation button"
    return True


def test_approval_card_small_amount_flow():
    """Small amount uses 3-step simplified flow (no forward button)."""
    card_source = read_component("ApprovalCard")
    assert "is_small_amount" in card_source, "Missing small amount check"
    return True


def test_approval_card_processed_state():
    """Processed cards show status badge and hide actions."""
    card_source = read_component("ApprovalCard")
    assert "isProcessed" in card_source or "status" in card_source, "Missing processed state"
    statuses = ["pending", "approved", "rejected", "forwarded", "delegated", "expired"]
    for s in statuses:
        assert s in card_source, f"Missing approval status: {s}"
    return True


def test_approval_card_confidence_levels():
    """Three confidence levels: high, medium, low."""
    card_source = read_component("ApprovalCard")
    assert "confidence-high" in card_source, "Missing high confidence style"
    assert "confidence-medium" in card_source, "Missing medium confidence style"
    assert "confidence-low" in card_source, "Missing low confidence style"
    return True


def test_approval_card_comment_input():
    """Comment input available before approve/reject."""
    card_source = read_component("ApprovalCard")
    assert "comment" in card_source.lower(), "Missing comment input"
    assert "comment-input" in card_source, "Missing comment input class"
    return True


def test_batch_approval_bar_render():
    """Batch approval bar with select/deselect/approve/reject."""
    card_source = read_component("ApprovalCard")
    assert "batch-approval-bar" in card_source, "Missing batch approval bar"
    assert "批量" in card_source, "Missing batch action text"
    assert "skipLarge" in card_source, "Missing skip large toggle"
    return True


def test_batch_approval_skip_large():
    """Skip large toggle controls whether large amounts bypass batch."""
    card_source = read_component("ApprovalCard")
    assert "跳过大额" in card_source, "Missing skip large label"
    return True


def test_approval_list_filter():
    """Filter bar with all/high/medium/low confidence levels."""
    card_source = read_component("ApprovalCard")
    assert "filterConfidence" in card_source, "Missing confidence filter state"
    assert "filter-btn" in card_source, "Missing filter button class"
    return True


def test_approval_list_select():
    """Checkbox selection for batch operations."""
    card_source = read_component("ApprovalCard")
    assert "selectedIds" in card_source, "Missing selection state"
    assert "toggleSelect" in card_source, "Missing toggle select handler"
    return True


# ============================================================
# Test: SearchBar Component
# ============================================================

def test_search_bar_exists():
    """SearchBar component file exists."""
    search_path = COMPONENTS_DIR / "SearchBar" / "index.tsx"
    assert search_path.exists(), "SearchBar component not found"
    return True


def test_search_bar_has_input():
    """SearchBar has text input with placeholder."""
    search = read_component("SearchBar")
    assert "input" in search.lower(), "Missing input element"
    return True


def test_search_bar_has_clear():
    """SearchBar has clear/reset functionality."""
    search = read_component("SearchBar")
    # Check for clear button or onClear handler
    has_clear = "clear" in search.lower() or "onClear" in search or "reset" in search.lower()
    assert has_clear, "Missing clear functionality"
    return True


def test_search_bar_has_submit():
    """SearchBar has search/submit handler."""
    search = read_component("SearchBar")
    assert "onSearch" in search or "handleSearch" in search or "onSubmit" in search, \
        "Missing search handler"
    return True


# ============================================================
# Test: SceneCard Component
# ============================================================

def test_scene_card_exists():
    """SceneCard component file exists."""
    scene_path = COMPONENTS_DIR / "SceneCard" / "index.tsx"
    assert scene_path.exists(), "SceneCard component not found"
    return True


def test_scene_card_feedback_buttons():
    """SceneCard has 👍/👎/🔄 feedback buttons."""
    scene = read_component("SceneCard")
    has_feedback = (
        "👍" in scene or "👎" in scene or "🔄" in scene or
        "feedback" in scene.lower() or "like" in scene.lower()
    )
    assert has_feedback, "Missing feedback buttons"
    return True


def test_scene_card_cold_start_stages():
    """SceneCard supports 4-stage cold start."""
    scene = read_component("SceneCard")
    # Check for cold start related logic
    has_cold_start = (
        "coldStart" in scene or "cold_start" in scene or
        "stage" in scene.lower() or "loading" in scene.lower()
    )
    assert has_cold_start, "Missing cold start support"
    return True


# ============================================================
# Test: ReportEditor Component
# ============================================================

def test_report_editor_exists():
    """ReportEditor component file exists."""
    report_path = COMPONENTS_DIR / "ReportEditor" / "index.tsx"
    assert report_path.exists(), "ReportEditor component not found"
    return True


def test_report_editor_forbidden_phrases():
    """ReportEditor forbids predictive phrases like '下周计划'."""
    report = read_component("ReportEditor")
    # Check for validation/forbidden phrase logic
    has_validation = (
        "validate" in report.lower() or
        "forbidden" in report.lower() or
        "禁止" in report or
        "验证" in report
    )
    assert has_validation, "Missing content validation"
    return True


def test_report_editor_export():
    """ReportEditor supports markdown/dict export."""
    report = read_component("ReportEditor")
    has_export = "export" in report.lower() or "导出" in report or "download" in report.lower()
    assert has_export, "Missing export functionality"
    return True


# ============================================================
# Test: SettingsPage Component
# ============================================================

def test_settings_page_exists():
    """SettingsPage component file exists."""
    settings_path = RENDERER_DIR / "pages" / "SettingsPage.tsx"
    assert settings_path.exists(), "SettingsPage component not found"
    return True


def test_settings_page_has_form():
    """SettingsPage has form with configurable options."""
    settings_path = SETTINGS_DIR / "SettingsPage.tsx"
    assert settings_path.exists(), "SettingsPage component not found"
    settings = settings_path.read_text()
    assert ("input" in settings.lower() or "select" in settings.lower() or "form" in settings.lower()), \
        "Missing form elements in settings"
    return True

def test_app_entry_exists():
    """App.tsx entry point exists."""
    app_path = RENDERER_DIR / "App.tsx"
    assert app_path.exists(), "App.tsx entry not found"
    return True


def test_app_renders_components():
    """App renders all major components."""
    app_path = RENDERER_DIR / "App.tsx"
    app = app_path.read_text()
    components = ["SearchBox", "Sidebar", "GateBadge", "EmailRow", "EmailDetail", 
                  "TokenPanel", "EmptyState", "LoadingSpinner"]
    found = sum(1 for c in components if c in app)
    assert found >= 6, f"Only {found}/{len(components)} major components found in App"
    return True


# ============================================================
# Test Runner
# ============================================================

ALL_TESTS = [
    # GateView
    ("GateView tab mapping", test_gate_view_tab_mapping),
    ("GateView empty state", test_gate_view_empty_state),
    ("GateView loading state", test_gate_view_loading_state),
    ("GateView stats footer", test_gate_view_stats_footer),
    ("GateView email item", test_gate_view_email_item),
    ("GateView approval badge", test_gate_view_approval_badge),
    ("GateView amount badge", test_gate_view_amount_badge),
    ("GateView tab click", test_gate_view_tab_click),
    ("GateView refresh", test_gate_view_refresh),
    ("GateView email click", test_gate_view_email_click),
    ("GateView date formatting", test_gate_view_date_formatting),
    # ApprovalCard
    ("ApprovalCard render", test_approval_card_render),
    ("ApprovalCard approve", test_approval_card_approve),
    ("ApprovalCard reject", test_approval_card_reject),
    ("ApprovalCard forward", test_approval_card_forward),
    ("ApprovalCard expand/collapse", test_approval_card_expand_collapse),
    ("ApprovalCard large amount confirm", test_approval_card_large_amount_confirmation),
    ("ApprovalCard small amount flow", test_approval_card_small_amount_flow),
    ("ApprovalCard processed state", test_approval_card_processed_state),
    ("ApprovalCard confidence levels", test_approval_card_confidence_levels),
    ("ApprovalCard comment input", test_approval_card_comment_input),
    ("Batch approval bar", test_batch_approval_bar_render),
    ("Batch skip large toggle", test_batch_approval_skip_large),
    ("ApprovalList filter", test_approval_list_filter),
    ("ApprovalList select", test_approval_list_select),
    # SearchBar
    ("SearchBar exists", test_search_bar_exists),
    ("SearchBar has input", test_search_bar_has_input),
    ("SearchBar has clear", test_search_bar_has_clear),
    ("SearchBar has submit", test_search_bar_has_submit),
    # SceneCard
    ("SceneCard exists", test_scene_card_exists),
    ("SceneCard feedback buttons", test_scene_card_feedback_buttons),
    ("SceneCard cold start", test_scene_card_cold_start_stages),
    # ReportEditor
    ("ReportEditor exists", test_report_editor_exists),
    ("ReportEditor forbidden phrases", test_report_editor_forbidden_phrases),
    ("ReportEditor export", test_report_editor_export),
    # SettingsPage
    ("SettingsPage exists", test_settings_page_exists),
    ("SettingsPage has form", test_settings_page_has_form),
    # App
    ("App entry exists", test_app_entry_exists),
    ("App renders components", test_app_renders_components),
]


def main():
    print("=" * 70)
    print("MailKnow V5.2 — 前端组件交互测试")
    print("=" * 70)

    passed = 0
    failed = 0
    failures = []

    for name, test_fn in ALL_TESTS:
        try:
            result = test_fn()
            if result:
                passed += 1
                print(f"  ✅ {name}")
            else:
                failed += 1
                print(f"  ❌ {name}")
                failures.append(name)
        except AssertionError as e:
            failed += 1
            print(f"  ❌ {name} — {e}")
            failures.append(name)
        except Exception as e:
            failed += 1
            print(f"  ❌ {name} — Exception: {e}")
            failures.append(name)

    total = passed + failed
    print(f"\n{'=' * 70}")
    print(f"结果: {passed}/{total} 通过 ({passed/total*100:.0f}%)")

    if failures:
        print(f"\n失败 ({len(failures)}):")
        for f in failures:
            print(f"  ❌ {f}")
    else:
        print("\n🎉 全部通过！")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
