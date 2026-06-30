import os
import sys
import re
import logging

script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(script_dir)
os.chdir(backend_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from models.database import OrganizationProfile, SessionLocal
from sqlalchemy import func
from services.history_recorder import record_change

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


# ========== LLM Prompts ==========

MISSION_PROMPT = """从以下机构介绍文本中提取Mission Statement（使命宣言）。

机构名称：{org_name}

文本内容：
{text}

提取规则：
1. 找明确表达"使命/宗旨/目的"的句子或段落
2. 常见标志词："Our mission is", "We exist to", "Our purpose is", "dedicated to", "committed to"
3. 如果文本中没有明确的Mission Statement，返回空字符串
4. 只返回Mission Statement原文，不要添加解释
5. 长度控制在50-500字

输出格式（只返回这一行）：
MISSION: <提取的文本 或 空>
"""


PROGRAMS_PROMPT = """判断以下机构介绍文本是否提到具体的项目、事工、活动或服务。

机构名称：{org_name}

文本内容：
{text}

判断规则：
- 提到 programs, ministries, outreach, services, projects, initiatives, activities 等具体项目 → YES
- 只有一般性描述，没有具体项目 → NO
- 只有信仰声明或历史介绍，没有项目 → NO

输出格式（只返回这一行）：
HAS_PROGRAMS: YES 或 NO
"""


# ========== 正则提取 ==========

EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_PATTERN = re.compile(r"(?:\+\d{1,3}[\s-]?)?\(?\d{2,4}\)?[\s.-]?\d{2,4}[\s.-]?\d{2,4}")


def extract_email(text):
    """从文本中提取邮箱"""
    if not text:
        return None
    emails = EMAIL_PATTERN.findall(text)
    blacklist = [
        "example.com",
        "domain.com",
        "test.com",
        "sample.com",
        "noreply",
        "no-reply",
        "webmaster",
        "admin@",
        "info@example",
    ]
    for e in emails:
        e_lower = e.lower()
        if not any(b in e_lower for b in blacklist) and len(e) < 100:
            return e
    return None


def extract_phone(text):
    """从文本中提取电话"""
    if not text:
        return None
    phones = PHONE_PATTERN.findall(text)
    for p in phones:
        cleaned = re.sub(r"[^\d+]", "", p)
        if 7 <= len(cleaned) <= 15:
            return cleaned
    return None


def call_llm_simple(prompt, max_tokens=300):
    """简单LLM调用"""
    try:
        from services.llm_client import call_llm

        return call_llm(prompt, max_tokens=max_tokens, temperature=0.1)
    except Exception as e:
        logger.error(f"LLM调用失败: {e}")
        return None


def parse_llm_mission(response):
    """从LLM响应解析Mission"""
    if not response:
        return None
    match = re.search(r"MISSION:\s*(.+)", response, re.IGNORECASE | re.DOTALL)
    if match:
        text = match.group(1).strip()
        if text and text.lower() not in ["", "none", "空", "n/a", "null"]:
            return text[:500]
    return None


def parse_llm_programs(response):
    """从LLM响应解析Programs判断"""
    if not response:
        return False
    match = re.search(r"HAS_PROGRAMS:\s*(YES|NO)", response, re.IGNORECASE)
    if match:
        return match.group(1).upper() == "YES"
    return False


def batch_extract():
    """主函数：批量从已有文本提取字段"""
    db = SessionLocal()

    try:
        t1_total = db.query(OrganizationProfile).filter(OrganizationProfile.priority_tier == "T1").count()

        def count_field(field_name, is_bool=False):
            if is_bool:
                return (
                    db.query(OrganizationProfile)
                    .filter(
                        OrganizationProfile.priority_tier == "T1",
                        getattr(OrganizationProfile, field_name) == True,
                    )
                    .count()
                )
            return (
                db.query(OrganizationProfile)
                .filter(
                    OrganizationProfile.priority_tier == "T1",
                    getattr(OrganizationProfile, field_name) != None,
                    getattr(OrganizationProfile, field_name) != "",
                )
                .count()
            )

        print("=" * 50)
        print("开始前状态")
        print("=" * 50)
        print(f"description: {count_field('description')}/{t1_total}")
        print(f"about_text: {count_field('about_text')}/{t1_total}")
        print(f"mission_statement: {count_field('mission_statement')}/{t1_total}")
        print(f"has_programs: {count_field('has_programs', is_bool=True)}/{t1_total}")
        print(f"has_contact: {count_field('has_contact', is_bool=True)}/{t1_total}")
        print(f"contact_email: {count_field('contact_email')}/{t1_total}")
        print(f"phone_public: {count_field('phone_public')}/{t1_total}")

        from sqlalchemy import or_

        orgs = (
            db.query(OrganizationProfile)
            .filter(
                OrganizationProfile.priority_tier == "T1",
                OrganizationProfile.about_text != None,
                OrganizationProfile.about_text != "",
                or_(
                    OrganizationProfile.mission_statement == None,
                    OrganizationProfile.mission_statement == "",
                    OrganizationProfile.has_programs == None,
                    OrganizationProfile.has_programs == False,
                    OrganizationProfile.contact_email == None,
                    OrganizationProfile.contact_email == "",
                    OrganizationProfile.phone_public == None,
                    OrganizationProfile.phone_public == "",
                    OrganizationProfile.description == None,
                    OrganizationProfile.description == "",
                ),
            )
            .all()
        )

        print(f"\n找到 {len(orgs)} 家需要补齐的T1机构")

        mission_added = 0
        programs_added = 0
        email_added = 0
        phone_added = 0
        desc_added = 0
        skipped = 0

        for i, org in enumerate(orgs):
            if i % 10 == 0:
                print(f"  处理中... {i}/{len(orgs)}")

            text = org.about_text or ""
            if len(text) < 50:
                skipped += 1
                continue

            if not org.mission_statement:
                try:
                    prompt = MISSION_PROMPT.format(org_name=org.name, text=text[:3000])
                    response = call_llm_simple(prompt, max_tokens=300)
                    mission = parse_llm_mission(response)
                    if mission and len(mission) > 20:
                        old_mission = org.mission_statement
                        org.mission_statement = mission
                        mission_added += 1
                        record_change(
                            org_id=org.id,
                            field_name="mission_statement",
                            old_value=old_mission,
                            new_value=mission,
                            source="batch_text_extract",
                            changed_by="system",
                            db=db,
                        )
                        print(f"  [MISSION] {org.name}: {mission[:80]}...")
                except Exception as e:
                    logger.debug(f"Mission提取失败 {org.name}: {e}")

            if not org.has_programs:
                try:
                    prog_keywords = [
                        "program",
                        "ministry",
                        "ministries",
                        "outreach",
                        "service",
                        "project",
                        "initiative",
                        "activity",
                        "mission work",
                        "community",
                    ]
                    text_lower = text.lower()
                    has_prog = any(kw in text_lower for kw in prog_keywords)

                    if has_prog:
                        old_programs = org.has_programs
                        org.has_programs = True
                        programs_added += 1
                        record_change(
                            org_id=org.id,
                            field_name="has_programs",
                            old_value=old_programs,
                            new_value=True,
                            source="batch_text_extract",
                            changed_by="system",
                            db=db,
                        )
                        print(f"  [PROGRAMS] {org.name}: YES (keyword)")
                    else:
                        prompt = PROGRAMS_PROMPT.format(org_name=org.name, text=text[:2000])
                        response = call_llm_simple(prompt, max_tokens=100)
                        if parse_llm_programs(response):
                            old_programs = org.has_programs
                            org.has_programs = True
                            programs_added += 1
                            record_change(
                                org_id=org.id,
                                field_name="has_programs",
                                old_value=old_programs,
                                new_value=True,
                                source="batch_text_extract",
                                changed_by="system",
                                db=db,
                            )
                            print(f"  [PROGRAMS] {org.name}: YES (LLM)")
                except Exception as e:
                    logger.debug(f"Programs判断失败 {org.name}: {e}")

            if not org.contact_email:
                email = extract_email(text)
                if not email and org.official_website:
                    domain = (
                        org.official_website.replace("https://", "")
                        .replace("http://", "")
                        .split("/")[0]
                    )
                    if "." in domain and "example" not in domain and "wikipedia" not in domain:
                        pass
                if email:
                    old_email = org.contact_email
                    org.contact_email = email
                    email_added += 1
                    record_change(
                        org_id=org.id,
                        field_name="contact_email",
                        old_value=old_email,
                        new_value=email,
                        source="batch_text_extract",
                        changed_by="system",
                        db=db,
                    )
                    print(f"  [EMAIL] {org.name}: {email}")

            if not org.phone_public:
                phone = extract_phone(text)
                if phone:
                    old_phone = org.phone_public
                    org.phone_public = phone
                    phone_added += 1
                    record_change(
                        org_id=org.id,
                        field_name="phone_public",
                        old_value=old_phone,
                        new_value=phone,
                        source="batch_text_extract",
                        changed_by="system",
                        db=db,
                    )
                    print(f"  [PHONE] {org.name}: {phone}")

            if not org.description:
                desc = text[:500].strip()
                if len(desc) > 50:
                    old_desc = org.description
                    org.description = desc
                    desc_added += 1
                    record_change(
                        org_id=org.id,
                        field_name="description",
                        old_value=old_desc,
                        new_value=desc,
                        source="batch_text_extract",
                        changed_by="system",
                        db=db,
                    )
                    print(f"  [DESC] {org.name}: {desc[:80]}...")

        db.commit()

        print("\n" + "=" * 50)
        print("提取完成")
        print("=" * 50)
        print(f"Mission补充: {mission_added}")
        print(f"Programs标记: {programs_added}")
        print(f"Email提取: {email_added}")
        print(f"Phone提取: {phone_added}")
        print(f"Description补充: {desc_added}")
        print(f"跳过(文本太短): {skipped}")

        print("\n" + "=" * 50)
        print("结束后状态")
        print("=" * 50)
        print(f"description: {count_field('description')}/{t1_total} ({count_field('description')/t1_total*100:.1f}%)")
        print(
            f"mission_statement: {count_field('mission_statement')}/{t1_total} ({count_field('mission_statement')/t1_total*100:.1f}%)"
        )
        print(f"has_programs: {count_field('has_programs', is_bool=True)}/{t1_total} ({count_field('has_programs', is_bool=True)/t1_total*100:.1f}%)")
        print(f"contact_email: {count_field('contact_email')}/{t1_total} ({count_field('contact_email')/t1_total*100:.1f}%)")
        print(f"phone_public: {count_field('phone_public')}/{t1_total} ({count_field('phone_public')/t1_total*100:.1f}%)")

    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    batch_extract()
