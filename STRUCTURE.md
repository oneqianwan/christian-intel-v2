```text
christian-intel-v2/
├── docker-compose.yml          # PostgreSQL + Redis
├── VERSION.md                  # 版本记录
├── STRUCTURE.md               # 项目结构
├── backend/
│   ├── requirements.txt
│   ├── .env                    # DeepSeek API Key（不提交git）
│   ├── config.py
│   ├── main.py
│   ├── queue_client.py
│   ├── test_rss.py
│   ├── test_acceptance.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── database.py         # 8张表定义
│   │   └── schemas.py
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── chat.py
│   │   ├── conversations.py
│   │   ├── missions.py
│   │   └── diagnostics.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── intent_router.py
│   │   ├── knowledge.py
│   │   ├── collection.py
│   │   ├── delivery.py
│   │   ├── llm_client.py
│   │   ├── rss_scanner.py
│   │   ├── page_scraper.py
│   │   ├── deep_scraper.py
│   │   └── mission_runner.py
│   └── workers/
│       ├── __init__.py
│       └── collector.py
└── frontend/
    ├── package.json
    ├── vite.config.ts
    ├── tsconfig.json
    ├── index.html
    └── src/
        ├── main.tsx
        ├── App.tsx
        ├── index.css
        ├── components/
        │   ├── Layout.tsx
        │   ├── Sidebar.tsx
        │   ├── ChatArea.tsx
        │   └── MessageItem.tsx
        ├── stores/
        │   ├── conversationStore.ts
        │   ├── messageStore.ts
        │   └── executionStore.ts
        └── services/
            ├── api.ts
            └── missionApi.ts
```
