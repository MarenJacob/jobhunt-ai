import io
from docx import Document
from app.services.resume_parser import extract_text, parse_resume

BASE = """MAREN DANJUMA
AI Application Developer & Product Designer
Jos, Plateau State, Nigeria | marendanjuma38@gmail.com | 08138183094
github.com/MarenJacob
TECHNICAL SKILLS
Python, PHP, SQL
EDUCATION
B.Sc. Computer Science, Plateau State University, Bokkos
2019 - 2024
LANGUAGES
English, Hausa
EXPERIENCE
Freelance Web Developer, 2023 - 2025"""


def test_sections_do_not_leak():
    p = parse_resume(BASE)
    assert p["name"] == "Maren Danjuma"
    assert p["phone"] == "08138183094" and p["email"].endswith("@gmail.com")
    assert "Python" in p["skills"] and "Plateau" not in p["skills"]
    assert "Plateau State University" in p["education"] and "Python" not in p["education"]
    assert "Hausa" not in p["education"]
    assert p["location"].startswith("Jos")


def test_table_layout_docx():
    d = Document(); t = d.add_table(rows=1, cols=2); L, R = t.rows[0].cells
    L.text = "MAREN DANJUMA\nSKILLS\nPython, PHP\nLANGUAGES\nEnglish"
    R.text = "EDUCATION\nB.Sc. Computer Science, PLASU\nEXPERIENCE\nFreelance Developer"
    buf = io.BytesIO(); d.save(buf)
    p = parse_resume(extract_text("cv.docx", buf.getvalue()))
    assert p["skills"] == "Python, PHP"
    assert p["education"] == "B.Sc. Computer Science, PLASU"


class FakeAI:
    def generate_json(self, prompt):
        return {"skills": ["Python", "PHP", "SQL"], "education": "Python, PHP, SQL", "experience": "Invented CEO at Google"}


def test_ai_output_is_validated():
    p = parse_resume(BASE, FakeAI())
    assert "Plateau State University" in p["education"]      # duplicate of skills rejected
    assert "Google" not in p["experience"]                     # ungrounded text rejected
