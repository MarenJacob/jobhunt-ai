import json
from ..config import settings

class AIService:
    def __init__(self):
        self.client = None
        if settings.openai_api_key:
            from openai import OpenAI
            self.client = OpenAI(api_key=settings.openai_api_key)

    def _chat(self, system: str, user: str):
        if not self.client:
            return None
        response = self.client.chat.completions.create(
            model=settings.openai_model,
            temperature=0.2,
            messages=[{"role":"system","content":system},{"role":"user","content":user}],
        )
        return response.choices[0].message.content

    def generate_json(self, prompt: str):
        raw = self._chat("You extract structured facts from resumes. Return JSON only. Never invent missing information.", prompt)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None

    def tailor(self, profile: dict, job: dict):
        prompt = f"""Candidate profile:\n{json.dumps(profile, ensure_ascii=False)}\n\nJob:\n{json.dumps(job, ensure_ascii=False)}\n\nReturn JSON with keys cover_letter, cv_summary, evidence_points, screening_questions. Never invent qualifications or experience. Keep cover_letter concise."""
        raw = self._chat("You are a truthful career application assistant. Optimize relevance, never fabricate.", prompt)
        if raw:
            try: return json.loads(raw)
            except Exception: pass
        return {"cover_letter": f"Hello {job.get('company','Hiring Team')},\n\nI’m applying for the {job.get('title','role')} position. My background in software development, AI/product work and hands-on project delivery aligns with the role. I would welcome the opportunity to discuss how I can contribute.\n\nBest regards,\n{profile.get('name','Candidate')}", "cv_summary": profile.get('headline',''), "evidence_points": [], "screening_questions": []}

    def interview(self, profile: dict, job: dict):
        raw = self._chat("You are an interview coach. Generate realistic, role-specific questions and a scoring rubric. Do not invent facts about the candidate.", f"Profile:{json.dumps(profile)}\nJob:{json.dumps(job)}")
        if raw: return raw
        return json.dumps({"questions":["Walk me through a project most relevant to this role.","Why are you interested in this company and role?","Describe a difficult technical problem you solved and how you validated the result."],"rubric":["specific evidence","technical reasoning","communication","ownership"]})
