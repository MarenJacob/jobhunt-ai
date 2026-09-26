import json
import re
from typing import Dict


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    import io
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


def _docx_text(data: bytes) -> str:
    from docx import Document
    import io
    doc = Document(io.BytesIO(data))
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text.strip() for cell in row.cells))
    return "\n".join(parts)


def extract_text(filename: str, data: bytes) -> str:
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        return _pdf_text(data)
    if name.endswith(".docx"):
        return _docx_text(data)
    raise ValueError("Only PDF and DOCX resumes are supported.")


def _section(text: str, *names: str) -> str:
    pattern = r"(?is)(?:^|\n)\s*(?:" + "|".join(re.escape(n) for n in names) + r")\s*[:\-]?\s*\n?(.*?)(?=\n\s*(?:professional profile|professional summary|core competencies|core skills|technical skills|skills|experience|professional experience|work experience|projects|selected projects|education|education & training|training|certifications|preferences|location)\s*[:\-]?\s*\n|\Z)"
    m = re.search(pattern, text)
    return m.group(1).strip() if m else ""


def _fallback(text: str) -> Dict[str, str]:
    lines = [x.strip(" •\t") for x in text.splitlines() if x.strip()]
    first = next((x for x in lines[:12] if re.fullmatch(r"[A-Za-z][A-Za-z .'-]{3,}", x) and len(x.split()) >= 2), "")
    email = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text)
    phone = re.search(r"(?:\+?\d[\d ()-]{8,}\d)", text)
    headline = next((x for x in lines[1:10] if "|" in x or "AI" in x or "Developer" in x or "Engineer" in x), "")
    skills = _section(text, "TECHNICAL SKILLS", "SKILLS", "CORE COMPETENCIES", "CORE SKILLS")
    experience = _section(text, "PROFESSIONAL EXPERIENCE", "EXPERIENCE", "WORK EXPERIENCE")
    projects = _section(text, "SELECTED PROJECTS", "PROJECTS")
    education = _section(text, "EDUCATION", "EDUCATION & TRAINING")
    profile = _section(text, "PROFESSIONAL PROFILE", "PROFESSIONAL SUMMARY", "SUMMARY")
    if not profile:
        profile = experience[:900]
    return {
        "name": first,
        "headline": headline,
        "email": email.group(0) if email else "",
        "location": "Nigeria" if "Nigeria" in text else "",
        "skills": skills,
        "projects": projects,
        "experience": experience,
        "education": education,
        "preferences": "junior, graduate, new grad, remote, Nigeria",
        "summary": profile,
        "phone": phone.group(0) if phone else "",
    }


def parse_resume(text: str, ai_service=None) -> Dict[str, str]:
    fallback = _fallback(text)
    if not ai_service:
        return fallback
    prompt = """Extract truthful candidate profile fields from this resume. Return ONLY valid JSON with these keys: name, headline, email, location, skills, projects, experience, education, preferences, summary, phone. Preserve facts and wording where useful. Never invent missing facts. Use concise plain text.\n\nRESUME:\n""" + text[:30000]
    try:
        raw = ai_service.generate_json(prompt)
        if isinstance(raw, dict):
            for k, v in fallback.items():
                if not str(raw.get(k) or "").strip(): raw[k] = v
            return {k: str(raw.get(k) or "") for k in fallback}
    except Exception:
        pass
    return fallback
