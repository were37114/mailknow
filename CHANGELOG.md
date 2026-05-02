# Changelog

All notable changes to MailKnow will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-05-01

### Added

#### Core Engine
- Gate rule-based email classifier (5 levels, 0 token)
- Tier 1-4 link extraction pipeline
- Auto Extractor for automatic entity building
- GBrain knowledge graph (Postgres + pgvector)
- Hybrid Search V2 (keyword + vector + metadata + RRF fusion)
- NL2SQL Translator (template + LLM + SQL injection protection)
- Batch Embedding async queue (bge-small-zh, local)
- Entity Aligner (threshold 0.7)
- compiled_truth compiler
- dead_letter queue
- Anomaly Detector (5 anomaly types)
- Attachment Extractor (PDF/Excel/CSV)
- Minion Worker framework

#### LLM & Degradation
- WithFallback async LLM client (3 strategies: RETRY_THEN_LOCAL, LOCAL_IMMEDIATELY, FAIL_FAST)
- TokenBudgetController V2 (monthly + daily budget, 4-level degradation)
- Desensitization Engine (6 types: person name, phone, email, ID card, amount, password)
- 200+ common Chinese surnames for person name detection
- Context-aware name validation with 2-char→1-char fallback

#### Approval Scene
- Dual-layer approval detection (Gate rules + LLM precision)
- ApprovalActions (create/approve/reject/forward/delegate/batch)
- CC approval detection with user_email support
- System forwarding detection ("系统转发" pattern)
- Large amount double confirmation (>¥100K)
- Confidence levels (HIGH/MEDIUM/LOW)

#### Report Scene
- Report Generator (sync + async modes)
- DeterministicValidator (forbidden prediction phrases)
- Markdown + dict export

#### Recommendation Scene
- SceneRecommender with 4-phase cold start (Day1/PostImport/Week1/Month1)
- RecommendationBoundary (max 5 cards/day, silent hours 22:00-08:00)
- Feedback flywheel (👍+0.1/👎-0.2+7-day cooldown/🔄demote)

#### Sync & Infrastructure
- IMAP sync engine with multi-account support
- Robustness (disconnect recovery, dedup)
- IPC Auth (random token + Unix Socket)
- Integrity Checker (7 checks)
- Telemetry Collector (18 events + PII desensitization)

#### API & Frontend
- FastAPI server with auth
- GateView 4-level frontend component
- SearchBar component
- Approval cards + batch approval UI
- Report editor
- Scene cards + feedback buttons
- Settings page
- Token budget panel

#### Testing
- 497 unit tests (100% pass)
- 4 performance benchmarks (Gate 2.16M/s, Search P95 0.1ms)
- 7/7 desensitization E2E tests (50/50 samples)
- 10/10 approval boundary tests (200/200 samples)
- 15 degradation tests
- 13 token budget tests
- 13 E2E approval closed-loop tests
- 11 E2E report generation tests
- 20 E2E scene recommendation tests
- 20 E2E knowledge search tests
- 28 desensitization unit tests

#### Infrastructure
- MIT License
- pyproject.toml (mailknow v1.0.0)
- macOS CI (Python 3.11/3.12, ruff + pytest)
- Windows build workflow
