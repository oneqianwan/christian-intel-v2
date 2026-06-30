"""
30个定向采集关键词 — Day 7
目标是命中“机构名录/列表”类页面，提高提取命中率
"""

PRESET_KEYWORDS = [
    {"label": "菲律宾教会名录", "keywords": ["list of Christian churches Philippines", "Philippines Christian organizations directory"], "country": "Philippines"},
    {"label": "菲律宾宣教机构", "keywords": ["Philippines mission organizations", "Philippines Christian ministries list"], "country": "Philippines"},
    {"label": "菲律宾神学院", "keywords": ["Philippines seminary theological school", "Bible school Philippines list"], "country": "Philippines"},
    {"label": "菲律宾FaithTech", "keywords": ["Philippines Christian technology", "FaithTech Philippines startup"], "country": "Philippines"},
    {"label": "菲律宾基金会", "keywords": ["Philippines Christian foundation", "Philippines evangelical charity"], "country": "Philippines"},
    {"label": "东南亚教会网络", "keywords": ["Southeast Asia Christian network", "Asia evangelical organization list"], "country": None},
    {"label": "新加坡基督教机构", "keywords": ["Singapore Christian organizations", "Singapore church directory"], "country": "Singapore"},
    {"label": "印尼教会联盟", "keywords": ["Indonesia Christian council", "Indonesia church federation list"], "country": "Indonesia"},
    {"label": "韩国大型教会", "keywords": ["South Korea mega church list", "Korea Christian ministry directory"], "country": "South Korea"},
    {"label": "印度基督教组织", "keywords": ["India Christian organizations", "India mission agencies list"], "country": "India"},
    {"label": "非洲宣教机构", "keywords": ["Africa Christian mission organizations", "Africa evangelical ministry list"], "country": None},
    {"label": "尼日利亚教会", "keywords": ["Nigeria Christian churches", "Nigeria Pentecostal church list"], "country": "Nigeria"},
    {"label": "肯尼亚基督教机构", "keywords": ["Kenya Christian organizations", "Kenya evangelical ministries"], "country": "Kenya"},
    {"label": "南非教会网络", "keywords": ["South Africa Christian council", "South Africa church directory"], "country": "South Africa"},
    {"label": "欧洲教会联盟", "keywords": ["Europe Christian organization list", "European evangelical alliance members"], "country": None},
    {"label": "英国基督教机构", "keywords": ["UK Christian charities list", "United Kingdom evangelical organizations"], "country": "United Kingdom"},
    {"label": "德国教会", "keywords": ["Germany Christian churches", "Germany evangelical ministry list"], "country": "Germany"},
    {"label": "拉美基督教机构", "keywords": ["Latin America Christian organizations", "Brazil evangelical church list"], "country": None},
    {"label": "巴西大型教会", "keywords": ["Brazil mega church", "Brazil Christian ministry directory"], "country": "Brazil"},
    {"label": "墨西哥基督教组织", "keywords": ["Mexico Christian organizations", "Mexico evangelical ministries"], "country": "Mexico"},
    {"label": "全球FaithTech公司", "keywords": ["FaithTech companies list", "Christian technology startups global"], "country": None},
    {"label": "全球圣经翻译机构", "keywords": ["Bible translation organizations", "Wycliffe affiliates list"], "country": None},
    {"label": "基督教媒体列表", "keywords": ["Christian media organizations list", "Christian news outlet directory"], "country": None},
    {"label": "基督教基金会全球", "keywords": ["Christian foundation grant", "evangelical funding organizations list"], "country": None},
    {"label": "青年事工机构", "keywords": ["Christian youth ministry organizations", "Christian student movement list"], "country": None},
    {"label": "祷告事工", "keywords": ["Christian prayer ministry organizations", "24-7 prayer movement"], "country": None},
    {"label": "反逼迫机构", "keywords": ["Christian persecution advocacy organizations", "religious freedom NGO list"], "country": None},
    {"label": "基督教大学", "keywords": ["Christian university college list", "evangelical higher education institutions"], "country": None},
    {"label": "基督教加速器孵化器", "keywords": ["Christian startup accelerator", "faith-based venture incubator"], "country": None},
    {"label": "基督教VC投资", "keywords": ["Christian venture capital", "faith-based investment fund"], "country": None},
]


def get_preset_keywords(index: int = None):
    """获取预设关键词"""
    if index is not None and 0 <= index < len(PRESET_KEYWORDS):
        return PRESET_KEYWORDS[index]
    return PRESET_KEYWORDS


def get_all_keywords_flat():
    """获取所有关键词的扁平列表（用于批量采集）"""
    all_keywords = []
    for preset in PRESET_KEYWORDS:
        all_keywords.extend(preset["keywords"])
    return all_keywords
