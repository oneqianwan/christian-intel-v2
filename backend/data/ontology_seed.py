"""
Christian Ontology 种子数据
"""

from models.database import (
    AIMaturityLevel,
    CollaborationPreference,
    OrganizationType,
    ScaleLevel,
    TheologicalPosition,
    get_db,
    init_db,
)


def seed_all():
    """初始化所有Ontology数据"""
    init_db()
    db = next(get_db())

    try:
        # 1. 机构类型
        org_types = [
            # 教会
            {"id": "church_independent", "name": "独立教会", "name_en": "Independent Church", "parent_id": None, "description": "不隶属于任何宗派或教会网络的独立教会"},
            {"id": "church_network", "name": "教会网络", "name_en": "Church Network", "parent_id": None, "description": "多堂点、统一品牌的教会体系（如Victory、CCF）"},
            {"id": "church_denomination", "name": "宗派体系教会", "name_en": "Denominational Church", "parent_id": None, "description": "属于传统宗派体系的教会（浸信会、圣公会等）"},
            {"id": "church_mega", "name": "大型教会", "name_en": "Mega Church", "parent_id": None, "description": "会众超过10000人的大型教会"},
            # 宣教机构
            {"id": "mission_agency", "name": "差传机构", "name_en": "Mission Agency", "parent_id": None, "description": "专注于跨文化宣教的机构（如OMF、YWAM）"},
            {"id": "mission_bible_translation", "name": "圣经翻译机构", "name_en": "Bible Translation Organization", "parent_id": None, "description": "专注于圣经翻译和语言事工（如Wycliffe）"},
            {"id": "mission_relief", "name": "救援/发展机构", "name_en": "Relief & Development", "parent_id": None, "description": "紧急救援和社区发展（如World Vision、CRS）"},
            # 基金会
            {"id": "foundation_grant", "name": "资助型基金会", "name_en": "Grant-making Foundation", "parent_id": None, "description": "通过资助项目支持基督教事工（如Maclellan Foundation）"},
            {"id": "foundation_investment", "name": "投资型基金会", "name_en": "Investment Foundation", "parent_id": None, "description": "以投资方式支持基督教创业（如Christian Venture Capital）"},
            {"id": "foundation_family", "name": "家族基金会", "name_en": "Family Foundation", "parent_id": None, "description": "家族设立的基督教基金会"},
            # FaithTech
            {"id": "faithtech_bible", "name": "圣经科技", "name_en": "Bible Tech", "parent_id": None, "description": "圣经应用、读经工具、经文查询（如YouVersion）"},
            {"id": "faithtech_worship", "name": "敬拜科技", "name_en": "Worship Tech", "parent_id": None, "description": "敬拜音乐、歌词投影、音频视频平台"},
            {"id": "faithtech_social", "name": "基督教社交媒体", "name_en": "Christian Social Media", "parent_id": None, "description": "面向基督徒的社交平台和内容社区"},
            {"id": "faithtech_fintech", "name": "基督教金融科技", "name_en": "Christian FinTech", "parent_id": None, "description": "基督教领域的金融科技应用"},
            {"id": "faithtech_ai", "name": "基督教AI", "name_en": "Christian AI", "parent_id": None, "description": "AI驱动的基督教产品（AI圣经助手、内容生成等）"},
            {"id": "faithtech_education", "name": "基督教教育科技", "name_en": "Christian EdTech", "parent_id": None, "description": "在线神学教育、门徒训练平台"},
            {"id": "faithtech_media", "name": "基督教媒体", "name_en": "Christian Media", "parent_id": None, "description": "基督教新闻、播客、视频制作"},
            # 其他
            {"id": "ngo_christian", "name": "基督教NGO", "name_en": "Christian NGO", "parent_id": None, "description": "非政府基督教组织"},
            {"id": "seminary", "name": "神学院", "name_en": "Seminary", "parent_id": None, "description": "神学教育机构"},
            {"id": "accelerator", "name": "加速器/孵化器", "name_en": "Accelerator/Incubator", "parent_id": None, "description": "基督教创业加速器和孵化器"},
            {"id": "media_outlet", "name": "基督教媒体机构", "name_en": "Christian Media Outlet", "parent_id": None, "description": "基督教新闻和媒体机构（如Christianity Today）"},
            {"id": "association", "name": "协会/联盟", "name_en": "Association/Alliance", "parent_id": None, "description": "基督教协会和联盟组织（如WEA、PCEC）"},
            {"id": "parachurch", "name": "跨教会事工机构", "name_en": "Parachurch Organization", "parent_id": None, "description": "服务多个教会或宗派的独立事工机构"},
        ]

        for item in org_types:
            existing = db.query(OrganizationType).filter(OrganizationType.id == item["id"]).first()
            if not existing:
                db.add(OrganizationType(**item))
        db.commit()
        print(f"✅ 机构类型: {len(org_types)} 条")

        # 2. 神学立场
        theologies = [
            {"id": "evangelical", "name": "福音派", "name_en": "Evangelical", "tradition": "protestant", "description": "强调圣经权威、个人归信、传福音"},
            {"id": "pentecostal", "name": "五旬节派", "name_en": "Pentecostal", "tradition": "protestant", "description": "强调圣灵恩赐、说方言、神医"},
            {"id": "charismatic", "name": "灵恩派", "name_en": "Charismatic", "tradition": "protestant", "description": "在五旬节派影响下，强调圣灵工作但不一定说方言"},
            {"id": "reformed", "name": "改革宗", "name_en": "Reformed", "tradition": "protestant", "description": "强调上帝主权、预定论、加尔文神学"},
            {"id": "baptist", "name": "浸信会", "name_en": "Baptist", "tradition": "protestant", "description": "强调信徒洗礼、地方教会自治"},
            {"id": "methodist", "name": "卫理公会", "name_en": "Methodist", "tradition": "protestant", "description": "强调成圣、社会公义、卫斯兰传统"},
            {"id": "anglican", "name": "圣公会", "name_en": "Anglican/Episcopal", "tradition": "protestant", "description": "英国国教传统，礼仪与福音并重"},
            {"id": "lutheran", "name": "路德宗", "name_en": "Lutheran", "tradition": "protestant", "description": "因信称义、路德神学传统"},
            {"id": "catholic", "name": "天主教", "name_en": "Catholic", "tradition": "catholic", "description": "罗马天主教传统，教皇权威"},
            {"id": "orthodox", "name": "东正教", "name_en": "Orthodox", "tradition": "orthodox", "description": "东方正教传统"},
            {"id": "nondenominational", "name": "无宗派", "name_en": "Non-denominational", "tradition": "protestant", "description": "不明确隶属于特定宗派"},
            {"id": "interdenominational", "name": "跨宗派", "name_en": "Interdenominational", "tradition": "protestant", "description": "跨越多个宗派的合作组织"},
        ]

        for item in theologies:
            existing = db.query(TheologicalPosition).filter(TheologicalPosition.id == item["id"]).first()
            if not existing:
                db.add(TheologicalPosition(**item))
        db.commit()
        print(f"✅ 神学立场: {len(theologies)} 条")

        # 3. 规模等级
        scales = [
            {"id": "micro", "name": "微型 (<100人)", "min_people": 0, "max_people": 100, "description": "小型教会或初创机构"},
            {"id": "small", "name": "小型 (100-1000人)", "min_people": 100, "max_people": 1000, "description": "中小型教会或机构"},
            {"id": "medium", "name": "中型 (1000-10000人)", "min_people": 1000, "max_people": 10000, "description": "中型教会网络或区域机构"},
            {"id": "large", "name": "大型 (10000-100000人)", "min_people": 10000, "max_people": 100000, "description": "大型教会或全国性机构"},
            {"id": "mega", "name": "超大型 (>100000人)", "min_people": 100000, "max_people": None, "description": "超大型教会网络或全球性机构"},
        ]

        for item in scales:
            existing = db.query(ScaleLevel).filter(ScaleLevel.id == item["id"]).first()
            if not existing:
                db.add(ScaleLevel(**item))
        db.commit()
        print(f"✅ 规模等级: {len(scales)} 条")

        # 4. AI成熟度
        ai_levels = [
            {"id": "level_0", "name": "无数字化", "description": "没有网站或社交媒体", "indicators": "仅线下活动，无在线存在"},
            {"id": "level_1", "name": "基础数字化", "description": "有网站和社交媒体", "indicators": "官网、Facebook/YouTube账号"},
            {"id": "level_2", "name": "数字化工具", "description": "使用CRM、管理系统等工具", "indicators": "教会管理软件、在线奉献系统"},
            {"id": "level_3", "name": "AI辅助", "description": "使用AI辅助工具", "indicators": "Chatbot、AI内容生成、智能推荐"},
            {"id": "level_4", "name": "AI原生", "description": "AI-first的产品和运营", "indicators": "核心产品由AI驱动，数据驱动决策"},
        ]

        for item in ai_levels:
            existing = db.query(AIMaturityLevel).filter(AIMaturityLevel.id == item["id"]).first()
            if not existing:
                db.add(AIMaturityLevel(**item))
        db.commit()
        print(f"✅ AI成熟度: {len(ai_levels)} 条")

        # 5. 合作偏好
        collab_prefs = [
            {"id": "seeking_investment", "name": "寻找投资", "description": "正在寻找投资方或融资"},
            {"id": "seeking_acquisition", "name": "寻找收购方", "description": "希望被收购或合并"},
            {"id": "open_partnership", "name": "开放合作", "description": "愿意与其他机构合作"},
            {"id": "making_investments", "name": "进行投资", "description": "有资金，正在寻找投资项目"},
            {"id": "seeking_projects", "name": "寻找项目", "description": "基金会/加速器寻找优质项目"},
            {"id": "not_open", "name": "暂不开放", "description": "当前不寻求外部合作"},
            {"id": "exploring", "name": "探索中", "description": "可能感兴趣，但需要进一步了解"},
        ]

        for item in collab_prefs:
            existing = db.query(CollaborationPreference).filter(CollaborationPreference.id == item["id"]).first()
            if not existing:
                db.add(CollaborationPreference(**item))
        db.commit()
        print(f"✅ 合作偏好: {len(collab_prefs)} 条")

        print("\n✅ Christian Ontology 初始化完成！")
    finally:
        db.close()


if __name__ == "__main__":
    seed_all()
