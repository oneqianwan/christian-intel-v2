"""
投资机构种子数据 — 阶段2 Day1
全球基督教投资机构 / 基金会 / 影响力投资 / 候选VC 50+ 家
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.database import Investor, get_db, init_db


INVESTORS = [
    # === 基督教基金会 ===
    {"name": "Maclellan Foundation", "name_en": "Maclellan Foundation", "investor_type": "foundation", "focus_areas": ["FaithTech", "Leadership", "Education"], "stage_focus": ["seed", "series_a"], "country": "美国", "region_focus": ["Global"], "website": "https://maclellanfoundation.org", "thesis": "支持全球基督教领袖和科技事工", "source": "manual_seed"},
    {"name": "Lilly Endowment", "name_en": "Lilly Endowment", "investor_type": "foundation", "focus_areas": ["Religion", "Education", "Community"], "stage_focus": ["grant"], "country": "美国", "region_focus": ["US"], "website": "https://lillyendowment.org", "source": "manual_seed"},
    {"name": "Templeton Religion Trust", "name_en": "Templeton Religion Trust", "investor_type": "foundation", "focus_areas": ["Science & Religion", "Technology", "Research"], "stage_focus": ["grant"], "country": "美国", "region_focus": ["Global"], "website": "https://templetonreligiontrust.org", "source": "manual_seed"},
    {"name": "Mustard Seed Foundation", "name_en": "Mustard Seed Foundation", "investor_type": "foundation", "focus_areas": ["Microenterprise", "Global South", "Church Planting"], "stage_focus": ["seed"], "country": "美国", "region_focus": ["Global South", "Southeast Asia", "Africa"], "website": "https://msfdn.org", "source": "manual_seed"},
    {"name": "Messiah Foundation", "name_en": "Messiah Foundation", "investor_type": "foundation", "focus_areas": ["Media", "Technology", "Mission"], "stage_focus": ["seed", "series_a"], "country": "美国", "region_focus": ["Global"], "source": "manual_seed"},
    {"name": "Stonebriar Foundation", "name_en": "Stonebriar Foundation", "investor_type": "foundation", "focus_areas": ["Mission", "Education", "Poverty Alleviation"], "stage_focus": ["grant"], "country": "美国", "region_focus": ["Global"], "source": "manual_seed"},
    {"name": "OneHope Foundation", "name_en": "OneHope Foundation", "investor_type": "foundation", "focus_areas": ["Children's Ministry", "Digital Media", "Global"], "stage_focus": ["grant", "seed"], "country": "美国", "region_focus": ["Global"], "website": "https://onehope.net", "source": "manual_seed"},
    {"name": "Global Gospel Ministries", "name_en": "Global Gospel Ministries", "investor_type": "foundation", "focus_areas": ["Media", "Technology", "Evangelism"], "stage_focus": ["grant"], "country": "美国", "region_focus": ["Global"], "source": "manual_seed"},
    {"name": "Seed Company", "name_en": "Seed Company", "investor_type": "foundation", "focus_areas": ["Bible Translation", "Technology", "Language"], "stage_focus": ["grant"], "country": "美国", "region_focus": ["Global South"], "website": "https://seedcompany.com", "source": "manual_seed"},
    {"name": "Wycliffe Bible Translators Fund", "name_en": "Wycliffe Bible Translators Fund", "investor_type": "foundation", "focus_areas": ["Bible Translation", "Language Technology", "Linguistics"], "stage_focus": ["grant"], "country": "美国", "region_focus": ["Global"], "website": "https://wycliffe.org", "source": "manual_seed"},
    {"name": "SIL International Fund", "name_en": "SIL International Fund", "investor_type": "foundation", "focus_areas": ["Language Technology", "Bible Translation", "Education"], "stage_focus": ["grant"], "country": "美国", "region_focus": ["Global"], "website": "https://sil.org", "source": "manual_seed"},
    {"name": "Bethlehem College & Seminary Fund", "name_en": "Bethlehem College & Seminary Fund", "investor_type": "foundation", "focus_areas": ["Education", "Theology", "Technology"], "stage_focus": ["grant"], "country": "美国", "region_focus": ["US"], "source": "manual_seed"},
    {"name": "Stewardship (UK)", "name_en": "Stewardship", "investor_type": "foundation", "focus_areas": ["Christian Giving", "Technology", "UK Ministry"], "stage_focus": ["seed", "grant"], "country": "英国", "region_focus": ["UK", "Europe"], "website": "https://stewardship.org.uk", "source": "manual_seed"},
    {"name": "National Christian Foundation", "name_en": "National Christian Foundation", "investor_type": "foundation", "focus_areas": ["Christian Giving", "Donor Advised Funds", "Ministry"], "stage_focus": ["grant"], "country": "美国", "region_focus": ["US"], "website": "https://nationalchristian.com", "source": "manual_seed"},
    {"name": "Christian Community Foundation", "name_en": "Christian Community Foundation", "investor_type": "foundation", "focus_areas": ["Giving", "Kingdom Ventures", "Family Office"], "stage_focus": ["grant", "seed"], "country": "美国", "region_focus": ["US"], "website": "https://christiancommunity.org", "source": "manual_seed"},
    {"name": "WaterStone", "name_en": "WaterStone", "investor_type": "foundation", "focus_areas": ["Generosity", "Mission", "Kingdom Venture"], "stage_focus": ["grant", "seed"], "country": "美国", "region_focus": ["US", "Global"], "website": "https://waterstone.org", "source": "manual_seed"},
    {"name": "Praxis Labs", "name_en": "Praxis Labs", "investor_type": "foundation", "focus_areas": ["Redemptive Entrepreneurship", "FaithTech", "Social Enterprise"], "stage_focus": ["seed"], "country": "美国", "region_focus": ["US", "Global"], "website": "https://praxislabs.org", "thesis": "专注救赎性创业，孵化 FaithTech 与社会企业", "source": "manual_seed"},
    {"name": "Halftime Institute", "name_en": "Halftime Institute", "investor_type": "foundation", "focus_areas": ["Leadership", "Social Enterprise", "Coaching"], "stage_focus": ["seed"], "country": "美国", "region_focus": ["Global"], "website": "https://halftimeinstitute.org", "source": "manual_seed"},
    {"name": "C12 Business Forums", "name_en": "C12 Business Forums", "investor_type": "foundation", "focus_areas": ["Faith-driven Business", "Leadership"], "stage_focus": ["seed"], "country": "美国", "region_focus": ["US"], "website": "https://c12forums.org", "source": "manual_seed"},
    {"name": "Faith Driven Investor Network", "name_en": "Faith Driven Investor Network", "investor_type": "angel", "focus_areas": ["FaithTech", "Kingdom Venture", "Consumer"], "stage_focus": ["pre_seed", "seed", "series_a"], "country": "美国", "region_focus": ["Global"], "website": "https://faithdriveninvestor.org", "source": "manual_seed"},
    {"name": "Faith Driven Entrepreneur Foundation", "name_en": "Faith Driven Entrepreneur Foundation", "investor_type": "foundation", "focus_areas": ["Entrepreneurship", "FaithTech", "Media"], "stage_focus": ["seed"], "country": "美国", "region_focus": ["Global"], "website": "https://faithdrivenentrepreneur.org", "source": "manual_seed"},

    # === FaithTech VC / PE / Angel ===
    {"name": "Draper Associates", "name_en": "Draper Associates", "investor_type": "vc", "focus_areas": ["FaithTech", "Consumer", "AI"], "stage_focus": ["seed", "series_a", "series_b"], "country": "美国", "region_focus": ["Global", "Southeast Asia"], "website": "https://draper.vc", "thesis": "Tim Draper 旗下，覆盖早期高增长消费与平台项目", "source": "manual_seed"},
    {"name": "Greylock Partners", "name_en": "Greylock Partners", "investor_type": "vc", "focus_areas": ["Consumer", "SaaS", "Marketplace"], "stage_focus": ["series_a", "series_b", "series_c"], "country": "美国", "region_focus": ["US", "Global"], "website": "https://greylock.com", "source": "manual_seed"},
    {"name": "a16z (Andreessen Horowitz)", "name_en": "Andreessen Horowitz", "investor_type": "vc", "focus_areas": ["Consumer", "Social", "AI"], "stage_focus": ["series_a", "series_b", "series_c"], "country": "美国", "region_focus": ["Global"], "website": "https://a16z.com", "source": "manual_seed"},
    {"name": "Lightspeed Venture Partners", "name_en": "Lightspeed Venture Partners", "investor_type": "vc", "focus_areas": ["Consumer", "Enterprise", "SaaS"], "stage_focus": ["seed", "series_a", "series_b"], "country": "美国", "region_focus": ["Global", "Southeast Asia"], "website": "https://lsvp.com", "source": "manual_seed"},
    {"name": "Bessemer Venture Partners", "name_en": "Bessemer Venture Partners", "investor_type": "vc", "focus_areas": ["Consumer", "Enterprise", "SaaS"], "stage_focus": ["series_a", "series_b", "series_c"], "country": "美国", "region_focus": ["Global"], "website": "https://bvp.com", "source": "manual_seed"},
    {"name": "Sequoia Capital", "name_en": "Sequoia Capital", "investor_type": "vc", "focus_areas": ["Consumer", "Enterprise", "AI"], "stage_focus": ["seed", "series_a", "series_b", "series_c"], "country": "美国", "region_focus": ["Global", "Southeast Asia"], "website": "https://sequoiacap.com", "source": "manual_seed"},
    {"name": "500 Global", "name_en": "500 Global", "investor_type": "vc", "focus_areas": ["Consumer", "SaaS", "Marketplace"], "stage_focus": ["seed", "series_a"], "country": "美国", "region_focus": ["Southeast Asia", "Global"], "website": "https://500.co", "source": "manual_seed"},
    {"name": "Sovereign's Capital", "name_en": "Sovereign's Capital", "investor_type": "vc", "focus_areas": ["FaithTech", "SaaS", "Marketplace"], "stage_focus": ["seed", "series_a"], "country": "美国", "region_focus": ["US", "Global", "Southeast Asia"], "website": "https://sovereignscapital.com", "thesis": "聚焦价值观驱动型创业者与信仰驱动企业", "source": "manual_seed"},
    {"name": "Kingdom Investment Network", "name_en": "Kingdom Investment Network", "investor_type": "angel", "focus_areas": ["FaithTech", "Social Enterprise", "Mission"], "stage_focus": ["pre_seed", "seed"], "country": "美国", "region_focus": ["Global"], "source": "manual_seed"},
    {"name": "Christian Angel Network", "name_en": "Christian Angel Network", "investor_type": "angel", "focus_areas": ["FaithTech", "EdTech", "Media"], "stage_focus": ["pre_seed", "seed"], "country": "美国", "region_focus": ["US", "Global"], "source": "manual_seed"},
    {"name": "Jerusalem Venture Partners", "name_en": "Jerusalem Venture Partners", "investor_type": "vc", "focus_areas": ["Technology", "Media", "Cybersecurity"], "stage_focus": ["series_a", "series_b"], "country": "以色列", "region_focus": ["Middle East", "Global"], "website": "https://jvpvc.com", "source": "manual_seed"},
    {"name": "Capria Ventures", "name_en": "Capria Ventures", "investor_type": "vc", "focus_areas": ["Impact", "FinTech", "EdTech"], "stage_focus": ["seed", "series_a"], "country": "美国", "region_focus": ["Global South", "Southeast Asia", "Africa"], "website": "https://capria.vc", "source": "manual_seed"},
    {"name": "Patamar Capital", "name_en": "Patamar Capital", "investor_type": "vc", "focus_areas": ["Impact", "Education", "Financial Inclusion"], "stage_focus": ["seed", "series_a"], "country": "新加坡", "region_focus": ["Southeast Asia"], "website": "https://patamar.com", "source": "manual_seed"},
    {"name": "Unitus Ventures", "name_en": "Unitus Ventures", "investor_type": "vc", "focus_areas": ["Impact", "EdTech", "HealthTech"], "stage_focus": ["seed", "series_a"], "country": "印度", "region_focus": ["South Asia", "Southeast Asia"], "website": "https://unitus.vc", "source": "manual_seed"},

    # === 基督教影响力投资 / 社会企业 ===
    {"name": "Impact Foundation", "name_en": "Impact Foundation", "investor_type": "impact_investor", "focus_areas": ["FaithTech", "Social Enterprise", "Global Health"], "stage_focus": ["seed", "series_a"], "country": "美国", "region_focus": ["Global South"], "website": "https://impactfound.org", "source": "manual_seed"},
    {"name": "Oikocredit", "name_en": "Oikocredit", "investor_type": "impact_investor", "focus_areas": ["Microfinance", "Social Enterprise", "Agriculture"], "stage_focus": ["series_a"], "country": "荷兰", "region_focus": ["Africa", "Asia", "Latin America"], "website": "https://oikocredit.coop", "source": "manual_seed"},
    {"name": "Oikocredit Asia", "name_en": "Oikocredit Asia", "investor_type": "impact_investor", "focus_areas": ["Microfinance", "Social Enterprise", "Agriculture"], "stage_focus": ["series_a"], "country": "新加坡", "region_focus": ["Southeast Asia", "South Asia"], "website": "https://oikocredit.coop", "source": "manual_seed"},
    {"name": "HOPE International", "name_en": "HOPE International", "investor_type": "impact_investor", "focus_areas": ["Microfinance", "Savings Groups", "Faith-based Enterprise"], "stage_focus": ["seed", "series_a"], "country": "美国", "region_focus": ["Africa", "Asia", "Latin America"], "website": "https://hopeinternational.org", "source": "manual_seed"},
    {"name": "Opportunity International", "name_en": "Opportunity International", "investor_type": "impact_investor", "focus_areas": ["Microfinance", "Education", "Agriculture"], "stage_focus": ["seed", "series_a"], "country": "美国", "region_focus": ["Africa", "Asia", "Latin America"], "website": "https://opportunity.org", "source": "manual_seed"},
    {"name": "Acumen", "name_en": "Acumen", "investor_type": "impact_investor", "focus_areas": ["Social Enterprise", "Education", "Energy"], "stage_focus": ["seed", "series_a"], "country": "美国", "region_focus": ["Africa", "South Asia", "Latin America"], "website": "https://acumen.org", "source": "manual_seed"},
    {"name": "Omidyar Network", "name_en": "Omidyar Network", "investor_type": "impact_investor", "focus_areas": ["Digital Society", "Education", "Consumer"], "stage_focus": ["series_a", "series_b"], "country": "美国", "region_focus": ["Global"], "website": "https://omidyar.com", "source": "manual_seed"},
    {"name": "Global Partnerships", "name_en": "Global Partnerships", "investor_type": "impact_investor", "focus_areas": ["Impact", "Agriculture", "Livelihood"], "stage_focus": ["series_a", "debt"], "country": "美国", "region_focus": ["Latin America", "Africa"], "website": "https://globalpartnerships.org", "source": "manual_seed"},
    {"name": "Triodos Investment Management", "name_en": "Triodos Investment Management", "investor_type": "impact_investor", "focus_areas": ["Impact", "Energy", "Financial Inclusion"], "stage_focus": ["series_a", "debt"], "country": "荷兰", "region_focus": ["Global"], "website": "https://triodos-im.com", "source": "manual_seed"},
    {"name": "BlueOrchard", "name_en": "BlueOrchard", "investor_type": "impact_investor", "focus_areas": ["Financial Inclusion", "Climate", "Impact"], "stage_focus": ["series_a", "debt"], "country": "瑞士", "region_focus": ["Global South"], "website": "https://blueorchard.com", "source": "manual_seed"},
    {"name": "responsAbility Investments", "name_en": "responsAbility Investments", "investor_type": "impact_investor", "focus_areas": ["Impact", "Climate", "Financial Inclusion"], "stage_focus": ["series_a", "debt"], "country": "瑞士", "region_focus": ["Asia", "Africa", "Latin America"], "website": "https://responsability.com", "source": "manual_seed"},
    {"name": "Sarona Asset Management", "name_en": "Sarona Asset Management", "investor_type": "impact_investor", "focus_areas": ["SME Growth", "Impact", "Emerging Markets"], "stage_focus": ["series_a", "series_b"], "country": "加拿大", "region_focus": ["Global South"], "website": "https://sarona.com", "source": "manual_seed"},
    {"name": "Transformational Business Network", "name_en": "Transformational Business Network", "investor_type": "impact_investor", "focus_areas": ["Faith-driven Business", "Kingdom Enterprise", "Impact"], "stage_focus": ["seed", "series_a"], "country": "英国", "region_focus": ["Global"], "website": "https://tbnetwork.org", "source": "manual_seed"},

    # === 教会/机构附属投资部门 ===
    {"name": "LifeWay Christian Resources", "name_en": "LifeWay Christian Resources", "investor_type": "corporate", "focus_areas": ["Christian Media", "EdTech", "Publishing"], "stage_focus": ["acquisition"], "country": "美国", "region_focus": ["US", "Global"], "thesis": "曾收购多家基督教科技工具", "website": "https://lifeway.com", "source": "manual_seed"},
    {"name": "Hillsong Church Ventures", "name_en": "Hillsong Church Ventures", "investor_type": "corporate", "focus_areas": ["Worship Tech", "Media", "Events"], "stage_focus": ["seed", "series_a"], "country": "澳大利亚", "region_focus": ["Global"], "thesis": "Hillsong 生态内的媒体与活动项目", "source": "manual_seed"},
    {"name": "Gloo", "name_en": "Gloo", "investor_type": "corporate", "focus_areas": ["FaithTech", "Data", "Church Tech"], "stage_focus": ["series_a", "series_b", "acquisition"], "country": "美国", "region_focus": ["US", "Global"], "website": "https://gloo.us", "source": "manual_seed"},
    {"name": "YouVersion Ecosystem Partners", "name_en": "YouVersion Ecosystem Partners", "investor_type": "corporate", "focus_areas": ["Bible Tech", "Consumer", "Media"], "stage_focus": ["seed", "series_a", "partnership"], "country": "美国", "region_focus": ["Global"], "website": "https://youversion.com", "source": "manual_seed"},

    # === 东南亚 / 菲律宾本地 ===
    {"name": "Philippine Council of Evangelical Churches (PCEC) Fund", "name_en": "PCEC Fund", "investor_type": "foundation", "focus_areas": ["Church Planting", "Mission", "Leadership"], "stage_focus": ["grant", "seed"], "country": "菲律宾", "region_focus": ["Philippines", "Southeast Asia"], "source": "manual_seed"},
    {"name": "Asian Enterprise Development Corporation", "name_en": "Asian Enterprise Development Corp", "investor_type": "impact_investor", "focus_areas": ["Microenterprise", "Community Development", "Faith-based"], "stage_focus": ["seed", "series_a"], "country": "菲律宾", "region_focus": ["Southeast Asia"], "source": "manual_seed"},
    {"name": "Alpha Southeast Asia", "name_en": "Alpha Southeast Asia", "investor_type": "foundation", "focus_areas": ["Church Planting", "Leadership", "Media"], "stage_focus": ["grant", "seed"], "country": "新加坡", "region_focus": ["Southeast Asia"], "source": "manual_seed"},
    {"name": "OMF International Fund", "name_en": "OMF International Fund", "investor_type": "foundation", "focus_areas": ["Mission", "East Asia", "Church Planting"], "stage_focus": ["grant"], "country": "新加坡", "region_focus": ["East Asia", "Southeast Asia"], "website": "https://omf.org", "source": "manual_seed"},
    {"name": "Asia Pacific Theological Seminary Fund", "name_en": "APTS Fund", "investor_type": "foundation", "focus_areas": ["Education", "Theology", "Leadership"], "stage_focus": ["grant"], "country": "菲律宾", "region_focus": ["Southeast Asia"], "source": "manual_seed"},
    {"name": "YWAM Foundation", "name_en": "YWAM Foundation", "investor_type": "foundation", "focus_areas": ["Mission", "Training", "Media"], "stage_focus": ["grant"], "country": "瑞士", "region_focus": ["Global"], "website": "https://ywam.org", "source": "manual_seed"},
    {"name": "Asian Access Fund", "name_en": "Asian Access Fund", "investor_type": "foundation", "focus_areas": ["Leadership", "Mission", "Asia Ministry"], "stage_focus": ["grant", "seed"], "country": "日本", "region_focus": ["East Asia", "Southeast Asia"], "website": "https://asianaccess.org", "source": "manual_seed"},
    {"name": "Faith Driven Philippines Network", "name_en": "Faith Driven Philippines Network", "investor_type": "angel", "focus_areas": ["FaithTech", "Media", "Leadership"], "stage_focus": ["pre_seed", "seed"], "country": "菲律宾", "region_focus": ["Philippines", "Southeast Asia"], "source": "manual_seed"},

    # === 更多全球候选机构 ===
    {"name": "Mastercard Foundation", "name_en": "Mastercard Foundation", "investor_type": "foundation", "focus_areas": ["Youth Employment", "Education", "Digital Access"], "stage_focus": ["grant"], "country": "加拿大", "region_focus": ["Africa", "Global"], "website": "https://mastercardfdn.org", "source": "manual_seed"},
    {"name": "Skoll Foundation", "name_en": "Skoll Foundation", "investor_type": "foundation", "focus_areas": ["Social Innovation", "Media", "Impact"], "stage_focus": ["grant", "series_a"], "country": "美国", "region_focus": ["Global"], "website": "https://skoll.org", "source": "manual_seed"},
    {"name": "Mulago Foundation", "name_en": "Mulago Foundation", "investor_type": "foundation", "focus_areas": ["Global Health", "Poverty", "Social Enterprise"], "stage_focus": ["grant", "seed"], "country": "美国", "region_focus": ["Global South"], "website": "https://mulagofoundation.org", "source": "manual_seed"},
    {"name": "Mercy Corps Ventures", "name_en": "Mercy Corps Ventures", "investor_type": "impact_investor", "focus_areas": ["FinTech", "Resilience", "Impact"], "stage_focus": ["seed", "series_a"], "country": "美国", "region_focus": ["Africa", "Asia"], "website": "https://mercycorpsventures.org", "source": "manual_seed"},
    {"name": "Octava Impact Investment", "name_en": "Octava Impact Investment", "investor_type": "impact_investor", "focus_areas": ["Education", "Health", "Impact"], "stage_focus": ["series_a"], "country": "新加坡", "region_focus": ["Southeast Asia"], "website": "https://octavafoundation.org", "source": "manual_seed"},
    {"name": "Blue Haven Initiative", "name_en": "Blue Haven Initiative", "investor_type": "impact_investor", "focus_areas": ["Impact", "Inclusive Finance", "Climate"], "stage_focus": ["series_a", "series_b"], "country": "美国", "region_focus": ["Global"], "website": "https://bluehaveninitiative.com", "source": "manual_seed"},
]


def seed_investors():
    init_db()
    session = next(get_db())

    try:
        print(f"[Seed] 开始写入投资机构种子数据... 共 {len(INVESTORS)} 家")
        inserted = 0
        for inv in INVESTORS:
            existing = session.query(Investor).filter(Investor.name == inv["name"]).first()
            if existing:
                continue
            session.add(Investor(**inv))
            inserted += 1

        session.commit()
        count = session.query(Investor).count()
        print(f"✅ 投资机构种子数据写入完成！新增: {inserted} 家，总计: {count} 家")
    except Exception as e:
        session.rollback()
        print(f"❌ 写入失败: {e}")
    finally:
        session.close()


if __name__ == "__main__":
    seed_investors()
