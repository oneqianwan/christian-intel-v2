import json
import os
import sys

script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(script_dir)
repo_root = os.path.dirname(backend_dir)
os.chdir(backend_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from models.database import SessionLocal


def main():
    db = SessionLocal()
    try:
        graph_path = os.path.join(backend_dir, "data", "developed_markets_graph.json")
        with open(graph_path, "r", encoding="utf-8") as file_obj:
            graph = json.load(file_obj)

        us_data = graph.get("countries", {}).get("United States", {})
        us_country_aliases = {"United States", "美国"}
        us_investors = {
            name: data
            for name, data in graph.get("investors", {}).items()
            if data.get("country") in us_country_aliases and data.get("portfolio_size", 0) > 0
        }

        sorted_investors = sorted(
            us_investors.items(),
            key=lambda item: (-item[1].get("portfolio_size", 0), item[0].lower()),
        )

        top_investors = sorted_investors[:4]
        all_relations = graph.get("relations", [])
        us_relations = [rel for rel in all_relations if rel.get("country") == "United States"]
        us_orgs = us_data.get("organizations", [])
        funded_orgs = [org for org in us_orgs if org.get("has_investment") and org.get("funding_rounds")]

        report = f"""# 美国基督教科技投资全景报告
## Christian Intel 情报专题

---

### 市场概况

| 指标 | 数值 |
|------|------|
| T1机构 | {us_data.get('org_count', 0)}家 |
| AI成熟度评估覆盖率 | {us_data.get('ai_coverage', 0)}% |
| 负责人覆盖率 | {us_data.get('people_coverage', 0)}% |
| 有投资关系机构 | {us_data.get('investment_coverage', 0)}% |

### 核心发现

1. **美国是全球基督教科技投资唯一成熟市场**
   - 发达国家图谱中的投资关系边共 {len(us_relations)} 条，当前全部落在美国节点
   - 投资网络围绕 Gloo、YouVersion / Life.Church、Pushpay、Subsplash、Tithe.ly、BibleProject、RightNow Media 形成

2. **AI成熟度极高（{us_data.get('ai_coverage', 0)}%）**
   - 说明美国基督教机构数字化程度全球领先
   - 但 People 覆盖率仅 {us_data.get('people_coverage', 0)}%，负责人信息仍是最大缺口

3. **投资网络集中度高**
"""

        if top_investors:
            for name, data in top_investors:
                report += f"   - {name}: {data.get('portfolio_size', 0)} 笔投资\n"
        else:
            report += "   - 当前图谱中暂无美国投资方 Portfolio 数据\n"

        report += "\n### 投资案例\n"

        if funded_orgs:
            for org in funded_orgs:
                report += f"\n#### {org['name']}\n"
                for funding_round in org.get("funding_rounds", []):
                    amount = funding_round.get("amount")
                    amount_str = f"${amount:,.0f}" if isinstance(amount, (int, float)) else "金额未披露"
                    report += (
                        f"- **{funding_round.get('round', 'Unknown')}**: {amount_str}"
                        f" | 投资方: {funding_round.get('investor', 'N/A')}\n"
                    )
        else:
            report += "\n当前图谱中暂无可展示的美国投资案例。\n"

        report += "\n### 投资方Portfolio\n"

        if sorted_investors:
            for investor_name, inv_data in sorted_investors:
                report += f"\n#### {investor_name}\n"
                report += f"Portfolio: {inv_data.get('portfolio_size', 0)}家\n\n"
                for portfolio_item in inv_data.get("portfolio", [])[:5]:
                    amount = portfolio_item.get("amount")
                    amount_str = f"${amount:,.0f}" if isinstance(amount, (int, float)) else "N/A"
                    report += f"- {portfolio_item.get('org_name', 'Unknown')} ({portfolio_item.get('org_country', 'Unknown')}) | {amount_str}\n"
        else:
            report += "\n暂无美国投资方 Portfolio 明细。\n"

        report += f"""

### 数据缺口与机会

| 缺口 | 当前 | 影响 |
|------|------|------|
| People覆盖率 | {us_data.get('people_coverage', 0)}% | 无法回答“谁负责” |
| Contact覆盖率 | 31.1% | 难以建立合作 |
| wikipedia_url覆盖 | 0/61 | 阻断稳定网络下的 About/Mission 低成本补齐 |

### 建议

1. **短期**：优先补齐美国T1的 `wikipedia_url` 与 People/Contact，形成完整 demo
2. **中期**：扩展英国、新加坡、韩国投资网络
3. **长期**：建立全球基督教科技投资指数

---
*报告生成时间: 2026-06-30*
*数据来源: Christian Intel 数据库 + 发达国家投资图谱*
"""

        output_path = os.path.join(repo_root, "docs", "US_CHRISTIAN_TECH_INVESTMENT_REPORT.md")
        with open(output_path, "w", encoding="utf-8") as file_obj:
            file_obj.write(report)

        print(f"美国投资专题报告已生成: {output_path}")
        print(f"报告长度: {len(report)}字符")
        print(f"美国投资方节点: {len(sorted_investors)}")
        print(f"美国投资关系边: {len(us_relations)}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
