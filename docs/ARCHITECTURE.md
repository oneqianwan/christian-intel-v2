# Christian Intel 架构地图

> 生成时间：自动生成

> 用途：每次给架构师参考代码结构


## 1. Python文件清单

- `backend\.tmp_final_verify.py`
- `backend\.tmp_final_verify_fixed.py`
- `backend\.tmp_p0_acceptance.py`
- `backend\.tmp_p0_acceptance_v2.py`
- `backend\.tmp_step4_final_clean.py`
- `backend\.tmp_wiki_batch.py`
- `backend\_tmp_architecture_gen.py`
- `backend\agent\__init__.py`
- `backend\agent\actions.py`
- `backend\agent\loop.py`
- `backend\agent\memory.py`
- `backend\agent\perception.py`
- `backend\agent\planner.py`
- `backend\agent\safety.py`
- `backend\config.py`
- `backend\crawlers\__init__.py`
- `backend\crawlers\arda_collector.py`
- `backend\crawlers\arda_denomination_collector.py`
- `backend\crawlers\dynamic_crawler.py`
- `backend\crawlers\fingerprint_spoofer.py`
- `backend\crawlers\infer_website_url.py`
- `backend\crawlers\joshua_project_collector.py`
- `backend\crawlers\pew_research_collector.py`
- `backend\crawlers\proxy_rotator.py`
- `backend\crawlers\rate_limiter.py`
- `backend\crawlers\smart_retry.py`
- `backend\crawlers\website_deep_crawler.py`
- `backend\crawlers\wiki_christian_collector.py`
- `backend\crawlers\wiki_website_extractor.py`
- `backend\cron_health_check.py`
- `backend\data\add_indexes.py`
- `backend\data\batch_collect.py`
- `backend\data\clean_org_profiles.py`
- `backend\data\clean_website_urls.py`
- `backend\data\clean_wiki_orgs.py`
- `backend\data\db_inventory.py`
- `backend\data\extract_relations_from_news.py`
- `backend\data\funding_rounds_seed.py`
- `backend\data\investor_seed.py`
- `backend\data\ontology_seed.py`
- `backend\data\preset_keywords.py`
- `backend\data\rss_global_seed.py`
- `backend\data\rss_global_seed_fix.py`
- `backend\data\schedule_daily.py`
- `backend\data\tag_existing_orgs.py`
- `backend\data\verify_website_urls.py`
- `backend\main.py`
- `backend\models\__init__.py`
- `backend\models\database.py`
- `backend\models\schemas.py`
- `backend\queue_client.py`
- `backend\routers\__init__.py`
- `backend\routers\agent.py`
- `backend\routers\bookmarks.py`
- `backend\routers\chat.py`
- `backend\routers\collection.py`
- `backend\routers\configs.py`
- `backend\routers\conversations.py`
- `backend\routers\dashboard.py`
- `backend\routers\diagnostics.py`
- `backend\routers\export.py`
- `backend\routers\feedback.py`
- `backend\routers\health.py`
- `backend\routers\missions.py`
- `backend\routers\search.py`
- `backend\routers\tasks.py`
- `backend\routers\url_analysis.py`
- `backend\routers\user_preferences.py`
- `backend\runtime_logs\acceptance_fix_temp.py`
- `backend\runtime_logs\add_kr_source_extra.py`
- `backend\runtime_logs\add_kr_sources.py`
- `backend\runtime_logs\cleanup_dirty_missions.py`
- `backend\runtime_logs\comparison_precision_test.py`
- `backend\runtime_logs\country_data_check.py`
- `backend\runtime_logs\e2e_collect_verify.py`
- `backend\runtime_logs\end2end_route_regression_verify.py`
- `backend\runtime_logs\final_acceptance_v210.py`
- `backend\runtime_logs\frontend_dialog_regression.py`
- `backend\runtime_logs\kr_backfill_run.py`
- `backend\runtime_logs\kr_backfill_run2.py`
- `backend\runtime_logs\kr_source_audit.py`
- `backend\runtime_logs\llm_enrich_ph_orgs.py`
- `backend\runtime_logs\monitor_backlog.py`
- `backend\runtime_logs\query_recent_comparisons.py`
- `backend\runtime_logs\route_regression_fix.py`
- `backend\runtime_logs\verify_clarify_mapping.py`
- `backend\runtime_logs\verify_clarify_mapping_fresh.py`
- `backend\runtime_logs\verify_composite_flow.py`
- `backend\runtime_logs\verify_conversation_api.py`
- `backend\scripts\batch_deep_crawl_t1.py`
- `backend\scripts\batch_extract_fields_from_text.py`
- `backend\scripts\batch_extract_people.py`
- `backend\scripts\batch_guess_urls.py`
- `backend\scripts\batch_update_urls.py`
- `backend\scripts\batch_update_urls_combined.py`
- `backend\scripts\bulk_manual_people_entry.py`
- `backend\scripts\export_t1_people_gaps.py`
- `backend\scripts\extract_people_from_text.py`
- `backend\scripts\extract_people_lightweight.py`
- `backend\scripts\mark_top300_priority.py`
- `backend\scripts\mark_url_tiers.py`
- `backend\scripts\wiki_people_extractor.py`
- `backend\services\__init__.py`
- `backend\services\agent.py`
- `backend\services\analysis.py`
- `backend\services\api_collectors.py`
- `backend\services\api_config_service.py`
- `backend\services\arda_batch.py`
- `backend\services\arda_collector.py`
- `backend\services\auto_extractor.py`
- `backend\services\brain.py`
- `backend\services\brain_planner.py`
- `backend\services\deep_scraper.py`
- `backend\services\delivery.py`
- `backend\services\domain_guesser.py`
- `backend\services\global_query.py`
- `backend\services\health_check.py`
- `backend\services\history_recorder.py`
- `backend\services\ingestion_guard.py`
- `backend\services\intent_router.py`
- `backend\services\knowledge.py`
- `backend\services\llm_client.py`
- `backend\services\llm_contact_extractor.py`
- `backend\services\mission_runner.py`
- `backend\services\news_page_scraper.py`
- `backend\services\org_profile_scraper.py`
- `backend\services\page_scraper.py`
- `backend\services\pdf_exporter.py`
- `backend\services\people_extractor.py`
- `backend\services\people_extractor_llm.py`
- `backend\services\people_validator.py`
- `backend\services\quality_scorer.py`
- `backend\services\rss_collector.py`
- `backend\services\rss_scanner.py`
- `backend\services\scoring.py`
- `backend\services\structured_crawler.py`
- `backend\services\telegram_collector.py`
- `backend\services\truth_engine.py`
- `backend\services\url_analyzer.py`
- `backend\services\wikidata_url_finder.py`
- `backend\services\wikipedia_url_extractor.py`
- `backend\services\youtube_collector.py`
- `backend\test_acceptance.py`
- `backend\test_rss.py`
- `backend\workers\__init__.py`
- `backend\workers\collector.py`


## 2. OrganizationProfile 字段定义

- `id`: VARCHAR
- `name`: VARCHAR
- `name_local`: VARCHAR
- `country`: VARCHAR
- `official_name`: VARCHAR
- `short_name`: VARCHAR
- `english_name`: VARCHAR
- `description`: TEXT
- `city`: VARCHAR
- `state_province`: VARCHAR
- `postal_code`: VARCHAR
- `mission_statement`: TEXT
- `vision_statement`: TEXT
- `statement_of_faith`: TEXT
- `official_website`: VARCHAR
- `contact_email`: VARCHAR
- `phone_public`: VARCHAR
- `address`: TEXT
- `headquarters_address`: VARCHAR
- `wikipedia_url`: VARCHAR
- `wikidata_id`: VARCHAR
- `google_maps_url`: VARCHAR
- `apple_maps_url`: VARCHAR
- `leader_name`: VARCHAR
- `leader_title`: VARCHAR
- `leader_bio_url`: VARCHAR
- `ai_team_lead`: VARCHAR
- `facebook_url`: VARCHAR
- `youtube_url`: VARCHAR
- `twitter_url`: VARCHAR
- `telegram_username`: VARCHAR
- `social_accounts_json`: TEXT
- `denomination`: VARCHAR
- `organization_type`: VARCHAR
- `denomination_category`: VARCHAR
- `organization_size`: VARCHAR
- `member_estimate`: INTEGER
- `founded_year`: INTEGER
- `member_count`: INTEGER
- `church_count`: INTEGER
- `employee_count`: INTEGER
- `volunteer_count`: INTEGER
- `languages`: TEXT
- `coverage_countries`: TEXT
- `service_countries`: TEXT
- `source_url`: VARCHAR
- `source_name`: VARCHAR
- `confidence`: FLOAT
- `tax_status`: VARCHAR
- `nonprofit_id`: VARCHAR
- `registration_number`: VARCHAR
- `annual_revenue`: VARCHAR
- `annual_expenses`: VARCHAR
- `budget_scale`: VARCHAR
- `has_ai_initiative`: BOOLEAN
- `has_online_giving`: BOOLEAN
- `has_mobile_app`: BOOLEAN
- `social_accounts`: JSON
- `key_activities`: JSON
- `ai_maturity_score`: INTEGER
- `digital_score`: INTEGER
- `about_text`: TEXT
- `tech_stack_json`: TEXT
- `ai_strategy`: TEXT
- `ai_projects`: TEXT
- `ai_news`: TEXT
- `ai_maturity_rationale`: TEXT
- `url_tier`: VARCHAR
- `priority_tier`: VARCHAR
- `last_website_crawl`: DATETIME
- `last_deep_crawl`: DATETIME
- `deep_crawl_status`: VARCHAR
- `pages_crawled`: TEXT
- `has_about`: BOOLEAN
- `has_mission`: BOOLEAN
- `has_vision`: BOOLEAN
- `has_leadership_page`: BOOLEAN
- `has_programs`: BOOLEAN
- `has_donate`: BOOLEAN
- `has_annual_report`: BOOLEAN
- `has_financial_report`: BOOLEAN
- `has_impact_report`: BOOLEAN
- `has_partner_page`: BOOLEAN
- `has_jobs`: BOOLEAN
- `has_events`: BOOLEAN
- `has_resources`: BOOLEAN
- `has_sermons`: BOOLEAN
- `has_podcast`: BOOLEAN
- `has_video`: BOOLEAN
- `has_blog`: BOOLEAN
- `has_press`: BOOLEAN
- `has_privacy`: BOOLEAN
- `has_contact`: BOOLEAN
- `data_sources_json`: TEXT
- `ingested_at`: DATETIME
- `updated_at`: DATETIME


## 3. API Endpoints


### __init__.py


### agent.py

- `POST /run`
- `GET /status`
- `GET /logs`

### bookmarks.py

- `POST /bookmarks`
- `GET /bookmarks`
- `DELETE /bookmarks/{bookmark_id}`

### chat.py

- `POST /chat/stream`
- `POST /chat/simple`

### collection.py

- `POST /start`
- `GET /status/{task_id}`
- `GET /recent`
- `GET /presets`

### configs.py

- `GET /configs/keys`

### conversations.py

- `POST /conversations`
- `GET /conversations`
- `PUT /conversations/{conversation_id}`
- `PUT /conversations/{conversation_id}/pin`
- `DELETE /conversations/{conversation_id}`
- `GET /conversations/{id}/messages`

### dashboard.py

- `GET /coverage`
- `GET /coverage/tier1`
- `GET /quality-scores`
- `GET /top-priority`
- `GET /tier-distribution`
- `GET /tier1-gaps`
- `POST /manual-update`
- `POST /inline-entry`
- `POST /inline-entry/bulk`
- `GET /recommend-next`
- `GET /people-candidates`
- `POST /people-candidates/review`
- `POST /quick-people-entry`
- `GET /overview`
- `GET /country-stats`
- `GET /history/summary`
- `GET /history/{org_id}`

### diagnostics.py

- `GET /diagnostics/request/{request_id}`

### export.py

- `GET /export/html`
- `GET /export/pdf`

### feedback.py

- `POST /feedback`
- `GET /feedback/stats`

### health.py

- `GET /health`
- `GET /health/sources`
- `GET /health/sources/{source_id}`

### missions.py

- `POST /missions`
- `GET /missions/{mission_id}`

### search.py

- `GET /search`

### tasks.py

- `GET /tasks`
- `POST /tasks`
- `DELETE /tasks/{task_id}`

### url_analysis.py

- `POST /analyze-url`

### user_preferences.py



## 4. Services 模块


### __init__.py


### agent.py

- `class AgentTask`
- `class CIOAgent`
- `def get_agent`
- `def submit_gap_collection`

### analysis.py

- `def resolve_entity_keyword`
- `def extract_entities`
- `def _build_field_filters`
- `def _build_faith_context_filters`
- `def _serialize_items`
- `def compare_entities`

### api_collectors.py

- `def _should_run_api_collectors`
- `def _mark_api_run`
- `def _get_or_create_api_source`
- `def _item_exists`
- `def _upsert_snapshot_item`
- `class NewsAPICollector`
- `class ScrapingBeeCollector`
- `class YouTubeCollector`
- `def run_all_api_collectors`

### api_config_service.py

- `def _derive_fernet_key`
- `def get_cipher`
- `def mask_key`
- `def ensure_api_config_schema`
- `def save_api_config`
- `def get_api_config`
- `def update_api_status`
- `def save_api_key`
- `def get_api_key`
- `def test_api_key`

### arda_batch.py

- `def batch_collect`

### arda_collector.py

- `def _normalize_text`
- `def _get_included_h2`
- `def _parse_primary_country_name`
- `def _parse_table_name`
- `def _extract_kv_table`
- `def _extract_religion_composition`
- `def _extract_summary_indicators`
- `def _extract_religion_state`
- `def fetch_arda_country`
- `def store_arda_data`
- `def collect_arda_priority_countries`

### auto_extractor.py

- `def _truncate_text`
- `def call_llm`
- `def _extract_json_blob`
- `def _guess_org_type`
- `def _heuristic_extract_organizations`
- `def _normalize_org_payload`
- `def _is_christian_relevant`
- `def _resolve_org_type_tag`
- `def hard_filter`
- `def extract_organizations_from_text`
- `def deduplicate_organizations`
- `def save_organization_with_tags`
- `def process_page_for_organizations`
- `def batch_extract_from_intelligence_items`

### brain.py

- `class Brain`
- `def think`

### brain_planner.py

- `class SubTask`
- `class PlanResult`
- `class QueryPlanner`
- `class ExecutiveReporter`
- `class BrainPlannerPipeline`
- `class AnalysisPatterns`
- `def detect_analysis_type`
- `def build_analysis_plan`

### deep_scraper.py

- `def _normalize_domain`
- `def deep_scrape_organization`

### delivery.py

- `def _generate_template_content`
- `def compose_delivery`

### domain_guesser.py

- `class DomainGuesser`
- `def guess_url_sync`

### global_query.py

- `def query_global_intelligence`

### health_check.py

- `def check_source_health`
- `def run_health_check`

### history_recorder.py

- `def record_change`
- `def record_org_changes`

### ingestion_guard.py

- `def _normalize_text`
- `def _map_source_type`
- `def is_duplicate`
- `def assess_item_quality`
- `def should_save`

### intent_router.py

- `def infer_scope`
- `def extract_keywords`
- `class IntentRouter`
- `def get_router`
- `def classify_intent`

### knowledge.py

- `def query_knowledge`

### llm_client.py

- `class LLMClient`
- `def call_llm`
- `def get_llm_client`

### llm_contact_extractor.py

- `def _fetch_page_html`
- `def fetch_page_text`
- `def _extract_json_from_text`
- `def extract_basic_from_homepage`
- `def _discover_candidate_pages`
- `def _choose_best_text_page`

### mission_runner.py

- `def _create_job_run`
- `def _finalize_job_run`
- `def _load_composite_meta`
- `def _resolve_mission_source_scope`
- `def _filter_sources_for_mission`
- `def _resolve_primary_status_source`
- `def notify_dialog_status_update`
- `def _execute_source_scan`
- `def run_with_timeout`
- `def _run_source_group`
- `def _get_composite_redis_client`
- `def _build_comparison_items`
- `def trigger_comparison`
- `def check_composite_completion`
- `def run_mission`

### news_page_scraper.py

- `def _normalize_url`
- `def _is_valid_article`
- `def _append_article`
- `def _find_heading_link`
- `def scrape_news_page`

### org_profile_scraper.py

- `def _normalize_text`
- `def _is_probable_person_name`
- `def _extract_emails`
- `def _pick_best_email`
- `def _extract_phones`
- `def _pick_best_phone`
- `def _extract_social_links`
- `def _find_candidate_links`
- `def _extract_leader_from_page`
- `def _extract_address_from_page`
- `def scrape_leadership_page`
- `def enrich_org_with_leader`
- `def scrape_org_website`
- `def store_organization_profile`

### page_scraper.py

- `def scrape_page`

### pdf_exporter.py

- `def generate_pdf_content`
- `def _resolve_wkhtmltopdf_path`
- `def html_to_pdf`

### people_extractor.py

- `class PersonInfo`
- `class PeopleExtractor`
- `class PeopleExtractorBatch`
- `def extract_people_sync`

### people_extractor_llm.py

- `class PersonLLM`
- `class PeopleExtractorLLM`
- `def extract_people_llm_sync`

### people_validator.py

- `class ValidationResult`
- `class PeopleValidator`

### quality_scorer.py

- `class QualityBreakdown`
- `class ProfileQualityScorer`
- `def get_t1_quality_summary`

### rss_collector.py

- `def _strip_html`
- `def _parse_entry_date`
- `def _ensure_source`
- `def parse_feed_safely`
- `def _request_feed`
- `def _candidate_urls`
- `def collect_rss`

### rss_scanner.py

- `def fetch_rss`
- `def _parse_date`

### scoring.py

- `def score_timeliness`
- `def score_source_influence`
- `def score_uniqueness`
- `def score_completeness`
- `def score_action_orientation`
- `def score_christian_relevance`
- `def score_content_penalty`
- `def calculate_score`
- `def get_scored_items`
- `def confidence_assessment`
- `def freshness_assessment`

### structured_crawler.py

- `class CrawlResult`
- `class DeepCrawlReport`
- `class StructuredCrawler`
- `def crawl_organization_sync`

### telegram_collector.py

- `def get_telegram_bot`
- `def _extract_username_from_source`
- `def collect_telegram_channel`

### truth_engine.py

- `class ConfidenceFactors`
- `class TruthEngine`

### url_analyzer.py

- `def detect_platform`
- `def extract_og_tags`
- `def _extract_script_text_by_id`
- `def analyze_url`

### wikidata_url_finder.py

- `def _normalize_name`
- `def _escape_sparql_string`
- `def _chunk`
- `class WikidataURLResult`
- `class WikidataURLFinder`
- `def find_urls_sync`
- `def find_urls_from_wikipedia_sync`

### wikipedia_url_extractor.py

- `def _is_http_url`
- `def _extract_title_from_wiki_url`
- `def _wikipedia_api_from_url`
- `class WikipediaURLExtractor`
- `def find_urls_from_wikipedia`

### youtube_collector.py

- `def get_youtube_client`
- `def _resolve_channel_id_by_search`
- `def _is_valid_channel_id`
- `def fetch_channel_videos`
- `def _extract_channel_id_from_source`
- `def collect_youtube_channel`


## 5. Scripts 脚本

- `backend\scripts\batch_deep_crawl_t1.py`
- `backend\scripts\batch_extract_fields_from_text.py`
- `backend\scripts\batch_extract_people.py`
- `backend\scripts\batch_guess_urls.py`
- `backend\scripts\batch_update_urls.py`
- `backend\scripts\batch_update_urls_combined.py`
- `backend\scripts\bulk_manual_people_entry.py`
- `backend\scripts\export_t1_people_gaps.py`
- `backend\scripts\extract_people_from_text.py`
- `backend\scripts\extract_people_lightweight.py`
- `backend\scripts\mark_top300_priority.py`
- `backend\scripts\mark_url_tiers.py`
- `backend\scripts\wiki_people_extractor.py`


## 6. Crawlers 采集器

- `backend\crawlers\__init__.py`
- `backend\crawlers\arda_collector.py`
- `backend\crawlers\arda_denomination_collector.py`
- `backend\crawlers\dynamic_crawler.py`
- `backend\crawlers\fingerprint_spoofer.py`
- `backend\crawlers\infer_website_url.py`
- `backend\crawlers\joshua_project_collector.py`
- `backend\crawlers\pew_research_collector.py`
- `backend\crawlers\proxy_rotator.py`
- `backend\crawlers\rate_limiter.py`
- `backend\crawlers\smart_retry.py`
- `backend\crawlers\website_deep_crawler.py`
- `backend\crawlers\wiki_christian_collector.py`
- `backend\crawlers\wiki_website_extractor.py`

## 7. Recovery Baseline

- Git 基线提交：`e480fc6`
- Git 标签：`pre-agent-upgrade-20260630-2005`
- Git 备份分支：`backup/pre-agent-upgrade-20260630-2005`
- 数据库备份：`backups/pre-agent-upgrade-20260630-200319/cio_intelligence.db`
- 项目 Zip 快照：`backups/pre-agent-upgrade-20260630-200319/project-code-snapshot.zip`
- 用途：作为 Agent 升级前的安全回退点，代码回退与数据回退需成对使用
