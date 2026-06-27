from datetime import datetime

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.orm import Session

from models.database import get_db, Source
from services.pdf_exporter import generate_pdf_content, html_to_pdf
from services.scoring import get_scored_items

router = APIRouter()


def _build_html(query: str, country: str, db: Session) -> str:
    items = get_scored_items(db, country=country, limit=15)
    execution_summary = {
        "sources_scanned": db.query(Source).filter(Source.country == country, Source.is_active == True).count(),
        "items_found": len(items),
        "countries": "菲律宾/美国/韩国/尼日利亚",
    }
    return generate_pdf_content(query, country, items, execution_summary)


@router.get("/export/html")
def export_html(query: str, country: str = "菲律宾", db: Session = Depends(get_db)):
    html_content = _build_html(query, country, db)
    return HTMLResponse(content=html_content)


@router.get("/export/pdf")
def export_pdf(query: str, country: str = "菲律宾", db: Session = Depends(get_db)):
    """导出PDF简报；若转换失败则降级返回HTML。"""
    html_content = _build_html(query, country, db)
    output_path = html_to_pdf(html_content)

    if output_path.lower().endswith(".pdf"):
        filename = f"christian_intel_brief_{country}_{datetime.now().strftime('%Y%m%d')}.pdf"
        return FileResponse(
            output_path,
            media_type="application/pdf",
            filename=filename,
        )

    return HTMLResponse(content=html_content)
