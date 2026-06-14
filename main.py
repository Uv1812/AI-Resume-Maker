from flask import Flask, render_template, request, jsonify, send_file
import os
import json
import re
from groq import Groq
from datetime import datetime


app = Flask(__name__)
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# ═══════════════════════════════════════════════════════════════════════
# A4 CSS + Pagination Engine
# paginator.js lives in static/paginator.js and is loaded once at startup.
# It runs INSIDE each resume iframe after fonts load, measures real heights,
# and inserts .rf-page-break markers between sections that overflow A4.
# ═══════════════════════════════════════════════════════════════════════

def _load_paginator_js() -> str:
    """Load the pagination engine from static/paginator.js."""
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, 'static', 'paginator.js')
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            return f.read()
    # Fallback: inline minimal version if file missing
    return ""

_PAGINATOR_JS = _load_paginator_js()


def _build_a4_block() -> str:
    """Build the <style> + <script> block injected into every resume."""
    css = """<style id="rf-a4">
@page {
  size: 210mm 297mm;
  margin: 0;
}
html {
  margin: 0 !important;
  padding: 0 !important;
  background: #e0e0e0 !important;
  overflow: visible !important;
  height: auto !important;
}
body {
  margin: 0 auto !important;
  padding: 0 !important;
  background: #e0e0e0 !important;
  overflow: visible !important;
  height: auto !important;
  -webkit-print-color-adjust: exact !important;
  print-color-adjust: exact !important;
}
@media print {
  html, body { background: #fff !important; }
  .rf-page-break {
    display: block !important;
    break-before: page !important;
    page-break-before: always !important;
    height: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
    border: none !important;
    box-shadow: none !important;
  }
}
/* Force A4 width on root container */
.page, .resume, .cv-wrap, .wrapper {
  width: 794px !important;
  max-width: 794px !important;
  min-width: 794px !important;
  overflow: visible !important;
  height: auto !important;
  margin: 0 auto !important;
  box-sizing: border-box !important;
  /* Remove clipping that hides multi-page content */
  border-radius: 0 !important;
}
/* Allow all layout containers to grow to natural height */
.body, .layout, .main, .main-col,
.sidebar, .left-col, .side-col, .right-col {
  overflow: visible !important;
  height: auto !important;
  min-height: 0 !important;
}
/* Print color accuracy */
* {
  -webkit-print-color-adjust: exact !important;
  print-color-adjust: exact !important;
}
/* Page-break CSS hints — reinforced by JS paginator */
.sec, .section, .sidebar-sec {
  break-inside: avoid !important;
  page-break-inside: avoid !important;
}
.item, .entry, .exp-item, .proj-item, .edu-item,
.card, .proj-card, .xcard, .edu-row,
.cert-row, .cert-item, .cert-it, .cert,
.proj, .edu, .xcard {
  break-inside: avoid !important;
  page-break-inside: avoid !important;
}
.sec-title, h1, h2, h3, h4 {
  break-after: avoid !important;
  page-break-after: avoid !important;
}
.hdr, .header, .top-bar, .hdr-inner {
  break-inside: avoid !important;
  page-break-inside: avoid !important;
}
.blist, .bl, .exp-bullets, ul {
  break-inside: avoid !important;
  page-break-inside: avoid !important;
}
/* Screen-only: page-break dividers inserted by JS */
@media screen {
  .rf-page-break {
    display: block !important;
    width: 100% !important;
    height: 24px !important;
    margin: 0 !important;
    padding: 0 !important;
    border-top: 3px dashed #bbb !important;
    border-bottom: none !important;
    background: #e8e8e8 !important;
    box-shadow: none !important;
    position: relative;
    z-index: 50;
    pointer-events: none;
  }
  .rf-page-break::before {
    content: 'Page Break';
    display: block;
    text-align: center;
    font-family: sans-serif;
    font-size: 10px;
    color: #999;
    line-height: 20px;
  }
}
</style>"""

    if _PAGINATOR_JS:
        script = f'\n<script id="rf-paginator">\n{_PAGINATOR_JS}\n</script>'
    else:
        script = ""

    return css + script


# Build once at startup
A4_CSS_BLOCK = _build_a4_block()


def inject_a4_css(html: str) -> str:
    """Inject A4 CSS + pagination engine just before </head>."""
    if '</head>' in html:
        return html.replace('</head>', A4_CSS_BLOCK + '\n</head>', 1)
    return html + A4_CSS_BLOCK

# ── AI Helpers ──────────────────────────────────────────────────────────────

def ai_enhance_summary(data: dict) -> str:
    prompt = f"""
You are an expert resume writer. Write a compelling 2-3 lines expressive objective for:
Name: {data.get('name')}
Role: {data.get('target_role')}
Experience: {data.get('experience_years')} years
Skills: {', '.join(data.get('skills', []))}
Key achievements: {data.get('achievements', 'Not provided')}

Write ONLY the 2-3 lines objective , no labels or extra text.
"""
    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=200, temperature=0.7,
    )
    return response.choices[0].message.content.strip() # type: ignore


def ai_enhance_bullet(job_title: str, company: str, raw_bullet: str) -> str:
    prompt = f"""
Rewrite this job bullet point to be stronger, quantified where possible, and ATS-optimized.
Job: {job_title} at {company}
Original: {raw_bullet}

Return ONLY the improved bullet point starting with a strong action verb. No extra text.
"""
    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=100, temperature=0.6,
    )
    return response.choices[0].message.content.strip() # type: ignore


def ai_suggest_skills(role: str, existing_skills: list) -> list:
    prompt = f"""
For a {role} position, suggest 8 additional relevant technical and soft skills.
Existing skills: {', '.join(existing_skills)}

Return ONLY a JSON array of skill strings, nothing else. Example: ["Skill1", "Skill2"]
"""
    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=150, temperature=0.5,
    )
    text = response.choices[0].message.content.strip() # type: ignore
    match = re.search(r'\[.*?\]', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except Exception:
            pass
    return []


def ai_ats_score(resume_data: dict, job_description: str) -> dict:
    raw_skills = resume_data.get('skills', [])
    skills_str = ', '.join(str(s) for s in raw_skills)

    exp_bullets = []
    for job in resume_data.get('experience', []):
        exp_bullets.extend(job.get('bullets', []))
    bullets_str = ' | '.join(exp_bullets[:10])

    proj_str = ' | '.join(
        f"{p.get('name','')} {p.get('tech_stack','')} {p.get('description','')}"
        for p in resume_data.get('projects', [])
    )

    prompt = f"""You are an ATS (Applicant Tracking System) expert.

Score this resume against the job description below.

RESUME DATA:
- Target Role: {resume_data.get('target_role', '')}
- Summary: {resume_data.get('summary', '')}
- Skills: {skills_str}
- Experience Bullets: {bullets_str}
- Projects: {proj_str}
- Certificates: {', '.join(str(c) for c in resume_data.get('certifications', []))}

JOB DESCRIPTION:
{job_description}

SCORING RULES:
1. Extract all keywords from the job description (skills, tools, technologies, qualifications,projects, certifications)
2. Check each keyword against ALL resume fields above
3. Partial matches count (React matches React.js, ML matches Machine Learning, DL matches Deep Learning, etc.)
4. score = round((matched_count / total_jd_keywords) * 100)
5. List at least 8 matched and 8 missing keywords

Return ONLY this JSON, no markdown, no extra text:
{{
  "score": <integer 0-100>,
  "matched_keywords": ["keyword1", "keyword2"],
  "missing_keywords": ["keyword1", "keyword2"],
  "suggestions": ["suggestion1", "suggestion2", "suggestion3"]
}}"""

    try:
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=600,
            temperature=0.1,
        )
        text = response.choices[0].message.content.strip() # type: ignore

        text = re.sub(r'```json\s*', '', text)
        text = re.sub(r'```\s*', '', text)
        text = text.strip()

        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group())

    except json.JSONDecodeError as e:
        print(f"ATS JSON parse error: {e}\nRaw response: {text}") # type: ignore
    except Exception as e:
        print(f"ATS error: {e}")

    return {"score": 0, "matched_keywords": [], "missing_keywords": [], "suggestions": []}


# ══════════════════════════════════════════════════════════════════
# RESUME TEMPLATE GENERATORS
# ══════════════════════════════════════════════════════════════════

def _build_contact_parts(data):
    parts = []
    if data.get('location'):
        parts.append(f'📍 {data["location"]}')

    if data.get('phone'):
        parts.append(f'📞 {data["phone"]}')

    if data.get('email'):
        parts.append(f'✉ {data["email"]}')

    # ==================== GITHUB ====================
    if data.get('github'):
        github = data['github'].strip()
        github = github.replace('https://github.com/', '').replace('www.github.com/', '').strip('/')
        github_url = f"https://github.com/{github}"
        parts.append(f'''
            <span style="color:inherit;">
                <svg width="17" height="17" viewBox="0 0 24 24" fill="currentColor" style="vertical-align:middle;">
                    <path d="M12 0C5.37 0 0 5.37 0 12c0 5.3 3.438 9.8 8.207 11.387.6.113.793-.26.793-.577 0-.285-.01-1.04-.016-2.04-3.338.726-4.042-1.416-4.042-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.09-.745.083-.73.083-.73 1.205.084 1.84 1.237 1.84 1.237 1.07 1.834 2.807 1.304 3.492.997.108-.775.42-1.305.764-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.4 3-.4 1.02 0 2.04.133 3 .4 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.43.37.81 1.096.81 2.22 0 1.605-.015 2.895-.015 3.285 0 .32.19.694.8.576C20.565 21.795 24 17.3 24 12c0-6.63-5.37-12-12-12z"/>
                </svg>
            </span>
            <a href="{github_url}" target="_blank" style="color:inherit; text-decoration:none;">{github}</a>
        ''')

    # ==================== LINKEDIN ====================
    if data.get('linkedin') and data.get('linkedinUser'):
        user = data['linkedinUser'].strip()
        linkedin_url = data['linkedin']
        parts.append(f'''
            <span style="color:inherit;">
                <svg width="17" height="17" viewBox="0 0 24 24" fill="currentColor" style="vertical-align:middle;">
                    <path d="M19 0H5a5 5 0 00-5 5v14a5 5 0 005 5h14a5 5 0 005-5V5a5 5 0 00-5-5zM8 19H5v-9h3v9zm-1.5-10.5a1.5 1.5 0 11.001-3.001 1.5 1.5 0 01-.001 3.001zM19 19h-3v-4.5c0-1.1-.9-2-2-2s-2 .9-2 2V19h-3v-9h3v1.2c.7-1.1 2-1.8 3.4-1.8 2.5 0 4.6 2.1 4.6 4.7V19z"/>
                </svg>
            </span>
            <a href="{linkedin_url}" target="_blank" style="color:inherit; text-decoration:none;">{user}</a>
        ''')

    return parts

def _build_education_html(education_list: list) -> str:
    """Clean Education HTML with proper alignment like your PDF sample"""
    if not education_list:
        return ""
    
    edu_html = ''
    for e in education_list:
        degree = e.get("degree", "").strip()
        institution = e.get("institution", "").strip()
        year = e.get("graduation_year", "").strip()
        gpa = e.get("gpa", "") or e.get("percentage", "")
        
        edu_html += f'''
        <div class="edu-item">
            <div class="edu-top-row">
                <span class="edu-degree">{degree}</span>
                <span class="edu-year">{year}</span>
            </div>
            <div class="edu-bottom-row">
                <span class="edu-institution">{institution}</span>
                {f'<span class="edu-gpa">{gpa}</span>' if gpa else ''}
            </div>
        </div>'''
    return edu_html

# ─── TEMPLATE 1: Executive Purple ─────────────────────────────
def template_executive(data: dict) -> str:
    contact = ' &nbsp;|&nbsp; '.join(_build_contact_parts(data))
    skills_html = ''.join(f'<span class="sk-pill">{s}</span>' for s in data.get('skills', []))

    exp_html = ''
    for job in data.get('experience', []):
        bullets = ''.join(f'<li>{b}</li>' for b in job.get('bullets', []) if b.strip())
        exp_html += f'''
        <div class="item">
          <div class="item-row">
            <div><div class="item-title">{job.get("title","")}</div>
            <div class="item-sub">{job.get("company","")}{(" &bull; " + job.get("location","")) if job.get("location") else ""}</div></div>
            <div class="item-date">{job.get("start_date","") or job.get("duration","")}{(" — " + job.get("end_date","Present")) if job.get("start_date") else ""}</div>
          </div>
          <ul class="blist">{bullets}</ul>
        </div>'''

    proj_html = ''
    for p in data.get('projects', []):
        link_html = f'<div style="margin-top:8px"><strong>Link :</strong> <a class="proj-link" href="{p.get("link")}" target="_blank">{p.get("link","")}</a></div>' if p.get("link") else ""
        proj_html += f'''
        <div class="item">
          <div class="item-row">
            <div><div class="item-title" style="font-size:15.5px;font-weight:700;margin-bottom:4px;">{p.get("name","")}</div>
            <div class="item-sub tech"><div class="i-sub tech"><strong>Technologies:</strong> {p.get("tech_stack","")}</div></div></div>
          </div>
          <p class="item-desc">{p.get("description","")}</p>
          {link_html}
        </div>'''

    edu_html = _build_education_html(data.get('education', []))

    cert_html = ''
    for c in data.get('certifications', []):
        name = c.get('name','') if isinstance(c, dict) else str(c)
        if name.strip():
            cert_html += f'<div class="cert-row">🏅 {name}</div>'

    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<title>{data.get("name","Resume")}</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;800&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:"Inter",sans-serif;background:#faf9ff;color:#1e1b2e;font-size:13.5px;line-height:1.65}}
.page{{max-width:850px;margin:30px auto;background:#fff;box-shadow:0 8px 40px rgba(107,33,168,.12);border-radius:4px;overflow:visible}}
.hdr{{background:linear-gradient(135deg,#4c1d95 0%,#6d28d9 60%,#7c3aed 100%);padding:44px 52px 36px;color:#fff}}
.hdr-name{{font-family:"Playfair Display",serif;font-size:46px;font-weight:800;letter-spacing:-1px;line-height:1}}
.hdr-role{{font-size:15px;font-weight:500;margin-top:6px;opacity:.85;letter-spacing:.5px}}
.hdr-contact{{margin-top:18px;font-size:12.5px;opacity:.8;display:flex;flex-wrap:wrap;gap:8px 16px}}
.hdr-contact a{{color:#e9d5ff;text-decoration:none}}
.body{{display:grid;grid-template-columns:200px 1fr;min-height:600px}}
.sidebar{{background:#f5f0ff;padding:32px 22px;border-right:1px solid #e9d5ff}}
.main{{padding:32px 40px}}
.sec-title{{font-size:10px;font-weight:700;letter-spacing:2.5px;text-transform:uppercase;color:#6d28d9;margin:0 0 14px;padding-bottom:6px;border-bottom:2px solid #ddd6fe}}
.sidebar .sec-title{{color:#4c1d95;border-color:#c4b5fd}}
.sk-pill{{display:block;font-size:12px;padding:5px 10px;margin-bottom:6px;background:#ede9fe;border-radius:6px;color:#4c1d95;font-weight:500}}
.item{{margin-bottom:22px}}
.item-row{{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:4px}}
.item-title{{font-size:14.5px;font-weight:600;color:#1e1b2e}}
.item-sub{{font-size:12.5px;color:#6b7280;margin-top:2px}}
.item-sub.tech{{color:#6d28d9;font-style:italic}}
.item-date{{font-size:11.5px;color:#7c3aed;font-weight:600;white-space:nowrap;flex-shrink:0}}
.blist{{padding-left:16px;margin-top:8px}}
.edu-item {{
    margin-bottom: 22px;
    padding-bottom: 12px;
    border-bottom: 1px solid #eee;
}}
.edu-item:last-child {{
    border-bottom: none;
    margin-bottom: 0;
    padding-bottom: 0;
}}

.edu-top-row {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 4px;
}}

.edu-degree {{
    font-size: 15px;
    font-weight: 600;
    color: #1e1b2e;
}}

.edu-year {{
    font-size: 13px;
    font-weight: 500;
    color: #666;
    white-space: nowrap;
}}

.edu-bottom-row {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
}}

.edu-institution {{
    font-size: 13.5px;
    color: #555;
}}

.edu-gpa {{
    font-size: 13px;
    font-weight: 600;
    color: #7c3aed;
}}
.blist li{{margin-bottom:5px;font-size:13px;color:#374151}}
.item-desc{{font-size:13px;color:#374151;margin-top:6px}}
.proj-link{{font-size:12px;color:#7c3aed;font-weight:600;text-decoration:none}}
.gpa{{font-size:12px;color:#6b7280;margin-top:4px}}
.cert-row{{font-size:13px;color:#374151;padding:4px 0;border-bottom:1px dashed #e5e7eb}}
.sidebar-sec{{margin-bottom:28px}}
@media print{{body{{background:#fff}}.page{{box-shadow:none;margin:0}}}}
</style></head><body>
<div class="page">
  <div class="hdr">
    <div class="hdr-name">{data.get("name","")}</div>
    <div class="hdr-role">{data.get("target_role","")}</div>
    <div class="hdr-contact">{contact}</div>
  </div>
  <div class="body">
    <div class="sidebar">
      {f'<div class="sidebar-sec"><div class="sec-title">Skills</div>{skills_html}</div>' if skills_html else ""}
      {f'<div class="sidebar-sec"><div class="sec-title">Languages</div><div style="font-size:12.5px;color:#374151;line-height:1.8">{data.get("languages","")}</div></div>' if data.get("languages") else ""}
      {f'<div class="sidebar-sec"><div class="sec-title">Tools</div><div style="font-size:12.5px;color:#374151;line-height:1.8">{data.get("tools","")}</div></div>' if data.get("tools") else ""}
      {f'<div class="sidebar-sec"><div class="sec-title">Soft Skills</div><div style="font-size:12.5px;color:#374151;line-height:1.8">{data.get("soft_skills","")}</div></div>' if data.get("soft_skills") else ""}
    </div>
    <div class="main">
      {f'<div style="margin-bottom:28px"><div class="sec-title">Objective</div><p style="font-size:13.5px;color:#374151;line-height:1.75">{data.get("summary","")}</p></div>' if data.get("summary") else ""}
      {f'<div style="margin-bottom:28px"><div class="sec-title">Experience</div>{exp_html}</div>' if exp_html else ""}
      {f'<div style="margin-bottom:28px"><div class="sec-title">Projects</div>{proj_html}</div>' if proj_html else ""}
      {f'<div style="margin-bottom:28px"><div class="sec-title">Education</div>{edu_html}</div>' if edu_html else ""}
      {f'<div style="margin-bottom:28px"><div class="sec-title">Certifications</div>{cert_html}</div>' if cert_html else ""}
    </div>
  </div>
</div></body></html>'''


# ─── TEMPLATE 2: Clean Minimal ─────────────────────────────
def template_minimal(data: dict) -> str:
    contact = ' · '.join(_build_contact_parts(data))
    skills = data.get('skills', [])
    skills_html = ''
    if skills:
        skill_items = ''.join(f'<div class="skill-item">• {s}</div>' for s in skills)
        skills_html = f'<div class="section"><div class="skills-list">{skill_items}</div></div>'

    exp_html = ''
    for job in data.get('experience', []):
        bullets = ''.join(f'<li>{b}</li>' for b in job.get('bullets', []) if b.strip())
        dur = job.get("start_date","") or job.get("duration","")
        end = f' – {job.get("end_date","Present")}' if job.get("start_date") else ""
        exp_html += f'''
        <div class="item">
          <div class="i-head"><span class="i-title">{job.get("title","")}</span><span class="i-date">{dur}{end}</span></div>
          <div class="i-sub">{job.get("company","")}{(", " + job.get("location","")) if job.get("location") else ""}</div>
          <ul class="blist">{bullets}</ul>
        </div>'''

    proj_html = ''
    for p in data.get('projects', []):
        link_html = f'<strong>Link :</strong> <a class="plink" href="{p.get("link")}" target="_blank">{p.get("link","")}</a><br><br>' if p.get("link") else ""
        proj_html += f'''
        <div class="item">
          <div class="i-head"><span class="i-title">{p.get("name","")}
          <div class="i-sub"><div class="i-sub tech"><strong>Technologies:</strong> {p.get("tech_stack","")}</div></div>
          <p class="i-desc">{p.get("description","")}</p>
          {link_html}
        </div>'''

    edu_html = _build_education_html(data.get('education', []))

    cert_items = ''
    for c in data.get('certifications', []):
        name = c.get('name','') if isinstance(c, dict) else str(c)
        if name.strip():
            cert_items += f'<div class="cert-row">🏅 {name}</div>'

    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<title>{data.get("name","Resume")}</title>
<link href="https://fonts.googleapis.com/css2?family=EB+Garamond:wght@400;500;600&family=DM+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:"DM Sans",sans-serif;background:#fff;color:#111;font-size:13.5px;line-height:1.6}}
.page{{max-width:820px;margin:30px auto;background:#fff;padding:52px 58px;overflow:visible}}
.name{{font-family:"EB Garamond",serif;font-size:48px;font-weight:600;letter-spacing:-1.5px;line-height:1}}
.role{{font-size:14px;color:#555;margin-top:5px;letter-spacing:.3px}}
.contact{{font-size:12.5px;color:#444;margin-top:10px;display:flex;flex-wrap:wrap;gap:6px 14px}}
.contact a{{color:#111;text-decoration:none}}
hr{{border:none;border-top:2px solid #111;margin:24px 0 16px}}
.sec-title{{font-size:12px;font-weight:700;letter-spacing:3px;text-transform:uppercase;color:#111;margin-bottom:14px}}
.item{{margin-bottom:18px}}
.i-head{{display:flex;justify-content:space-between;align-items:baseline;gap:10px}}
.i-title{{font-size:14px;font-weight:600;color:#111}}
.i-date{{font-size:12px;color:#666;flex-shrink:0}}
.i-sub{{font-size:12.5px;color:#555;margin:2px 0 6px}}
.blist{{padding-left:15px}}
.blist li{{margin-bottom:4px;font-size:13px;color:#333}}
.i-desc{{font-size:13px;color:#333;margin-top:4px}}
.plink{{font-size:12px;color:#333;text-decoration:underline}}
.skills-line{{font-size:13px;color:#333;line-height:1.8}}
.cert-chip{{display:inline-block;margin:0 8px 8px 0;font-size:12px;color:#111;border:1px solid #ccc;padding:3px 10px;border-radius:3px}}
.edu-item {{
    margin-bottom: 22px;
    padding-bottom: 12px;
    border-bottom: 1px solid #eee;
}}
.edu-item:last-child {{
    border-bottom: none;
    margin-bottom: 0;
    padding-bottom: 0;
}}

.edu-top-row {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 4px;
}}

.edu-degree {{
    font-size: 15px;
    font-weight: 600;
    color: #1e1b2e;
}}

.edu-year {{
    font-size: 13px;
    font-weight: 500;
    color: #666;
    white-space: nowrap;
}}

.edu-bottom-row {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
}}

.edu-institution {{
    font-size: 13.5px;
    color: #555;
}}

.edu-gpa {{
    font-size: 13px;
    font-weight: 600;
    color: #111;
}}
@media print{{.page{{margin:0;padding:36px 44px}}}}
</style></head><body>
<div class="page">
  <div class="name">{data.get("name","")}</div>
  <div class="role">{data.get("target_role","")}</div>
  <div class="contact">{contact}</div>
  {f'<hr><div class="sec-title">Profile</div><p style="font-size:13.5px;color:#333;line-height:1.75">{data.get("summary","")}</p>' if data.get("summary") else "<hr>"}
  {f'<hr><div class="sec-title">Experience</div>{exp_html}' if exp_html else ""}
  {f'<hr><div class="sec-title">Projects</div>{proj_html}' if proj_html else ""}
  {f'<hr><div class="sec-title">Education</div>{edu_html}' if edu_html else ""}
  {f'<hr><div class="sec-title">Skills</div><div class="skills-line">{skills_html}</div>' if skills_html else ""}
  {f'<hr><div class="sec-title">Certifications</div><div style="margin-top:4px">{cert_items}</div>' if cert_items else ""}
</div></body></html>'''


# ─── TEMPLATE 3: Modern Teal ─────────────────────────────
def template_modern(data: dict) -> str:
    contact_parts = _build_contact_parts(data)
    contact = ''.join(f'<div class="c-item">{p}</div>' for p in contact_parts)

    exp_html = ''
    for job in data.get('experience', []):
        bullets = ''.join(f'<li>{b}</li>' for b in job.get('bullets', []) if b.strip())
        dur = job.get("start_date","") or job.get("duration","")
        end = f' – {job.get("end_date","Present")}' if job.get("start_date") else ""
        exp_html += f'''
        <div class="card">
          <div class="card-accent"></div>
          <div class="card-body">
            <div class="card-top"><div class="ct-left"><div class="card-title">{job.get("title","")}</div>
            <div class="card-sub">{job.get("company","")}{(" · " + job.get("location","")) if job.get("location") else ""}</div></div>
            <div class="card-date">{dur}{end}</div></div>
            <ul class="blist">{bullets}</ul>
          </div>
        </div>'''

    proj_html = ''
    for p in data.get('projects', []):
        link_html = f'<div style="margin-top:8px"><strong>Link :</strong> <a class="proj-link" href="{p.get("link")}" target="_blank">{p.get("link","")}</a></div>' if p.get("link") else ""
        proj_html += f'''
        <div class="card">
          <div class="card-accent" style="background:#0d9488"></div>
          <div class="card-body">
            <div class="card-top"><div class="ct-left"><div class="card-title" style="font-size:15.5px;font-weight:700;margin-bottom:4px;">{p.get("name","")}</div>
            <div class="card-sub" style="color:#0d9488"><div class="i-sub tech"><strong>Technologies:</strong> {p.get("tech_stack","")}</div></div></div></div>
            <p class="card-desc">{p.get("description","")}</p>
            {link_html}
          </div>
        </div>'''

    # ==================== IMPROVED EDUCATION ====================
    edu_html = ''
    for e in data.get('education', []):
        degree = e.get("degree", "").strip()
        institution = e.get("institution", "").strip()
        year = e.get("graduation_year", "").strip()
        gpa = e.get("gpa", "") or e.get("percentage", "")

        edu_html += f'''
        <div class="edu-item">
            <div class="edu-bullet">🎓</div>
            <div class="edu-content">
                <div class="edu-top-row">
                    <span class="edu-degree">{degree}</span>
                    <span class="edu-year">{year}</span>
                </div>
                <div class="edu-bottom-row">
                    <span class="edu-institution">{institution}</span>
                    {f'<span class="edu-gpa">{gpa}</span>' if gpa else ''}
                </div>
            </div>
        </div>'''

    skills = data.get('skills', [])
    skills_html = ''
    if skills:
        skill_items = ''.join(f'<div class="skill-item">• {s}</div>' for s in skills)
        skills_html = f'<div class="section"><div class="skills-list">{skill_items}</div></div>'

    cert_html = ''
    for c in data.get('certifications', []):
        name = c.get('name','') if isinstance(c, dict) else str(c)
        if name.strip(): cert_html += f'<div class="cert-item">✔ {name}</div>'

    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<title>{data.get("name","Resume")}</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=Plus+Jakarta+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:"Plus Jakarta Sans",sans-serif;background:#f0fdfa;color:#134e4a;font-size:13.5px}}
.page{{max-width:850px;margin:30px auto;background:#fff;border-radius:12px;overflow:visible;box-shadow:0 8px 40px rgba(13,148,136,.15)}}
.top-bar{{background:linear-gradient(120deg,#0f766e,#0d9488,#14b8a6);padding:36px 48px;color:#fff}}
.t-name{{font-family:"Syne",sans-serif;font-size:44px;font-weight:800;letter-spacing:-1px}}
.t-role{{font-size:14px;opacity:.85;margin-top:4px;letter-spacing:.3px}}
.t-contact{{display:flex;flex-wrap:wrap;gap:8px 20px;margin-top:16px;font-size:12.5px;opacity:.85}}
.t-contact a{{color:#ccfbf1;text-decoration:none}}
.body{{display:grid;grid-template-columns:1fr 1fr;gap:0}}
.col{{padding:30px 36px}}
.col:first-child{{border-right:1px solid #f0fdfa}}
.sec-title{{font-size:10px;font-weight:700;letter-spacing:2.5px;text-transform:uppercase;color:#0d9488;margin:0 0 16px;display:flex;align-items:center;gap:8px}}
.sec-title::after{{content:"";flex:1;height:1.5px;background:#ccfbf1}}
.card{{display:flex;gap:0;margin-bottom:16px;border-radius:8px;overflow:hidden;border:1px solid #e6fffa}}
.card-accent{{width:4px;background:#0f766e;flex-shrink:0}}
.card-body{{padding:12px 14px;flex:1}}
.card-top{{display:flex;justify-content:space-between;align-items:flex-start;gap:8px;margin-bottom:6px}}
.card-title{{font-size:14px;font-weight:600;color:#134e4a}}
.card-sub{{font-size:12px;color:#6b7280;margin-top:2px}}
.card-date{{font-size:11.5px;color:#0d9488;font-weight:600;white-space:nowrap;flex-shrink:0}}
.card-desc{{font-size:12.5px;color:#374151;margin-top:4px}}
.blist{{padding-left:14px;margin-top:4px}}
.blist li{{font-size:12.5px;margin-bottom:4px;color:#374151}}
.proj-link{{font-size:12px;color:#0d9488;font-weight:600;text-decoration:none}}
.sk{{display:inline-block;margin:0 5px 5px 0;padding:4px 11px;background:#f0fdfa;border:1px solid #99f6e4;border-radius:20px;font-size:12px;color:#0f766e;font-weight:500}}
.cert-item{{font-size:12.5px;color:#374151;padding:5px 0;border-bottom:1px solid #f0fdfa}}
.summary-box{{background:#f0fdfa;border-left:4px solid #0d9488;padding:14px 16px;border-radius:0 8px 8px 0;font-size:13.5px;color:#134e4a;line-height:1.75;margin-bottom:20px}}

/* === EDUCATION STYLING === */
.edu-item {{
    display: flex;
    gap: 12px;
    margin-bottom: 20px;
    padding-bottom: 16px;
    border-bottom: 1px solid #e6fffa;
}}
.edu-item:last-child {{
    border-bottom: none;
    margin-bottom: 0;
    padding-bottom: 0;
}}
.edu-bullet {{
    font-size: 22px;
    line-height: 1;
    color: #0d9488;
    flex-shrink: 0;
    margin-top: 2px;
}}
.edu-content {{
    flex: 1;
}}
.edu-top-row {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 4px;
}}
.edu-degree {{
    font-size: 15px;
    font-weight: 600;
    color: #134e4a;
}}
.edu-year {{
    font-size: 13px;
    font-weight: 500;
    color: #0d9488;
    white-space: nowrap;
}}
.edu-bottom-row {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
}}
.edu-institution {{
    font-size: 13.2px;
    color: #555;
}}
.edu-gpa {{
    font-size: 13px;
    font-weight: 600;
    color: #0d9488;
}}

@media print{{body{{background:#fff}}.page{{box-shadow:none;margin:0;border-radius:0}}}}
</style></head><body>
<div class="page">
  <div class="top-bar">
    <div class="t-name">{data.get("name","")}</div>
    <div class="t-role">{data.get("target_role","")}</div>
    <div class="t-contact">{contact}</div>
  </div>
  <div style="padding:28px 36px 0">
    {f'<div class="sec-title">About</div><div class="summary-box">{data.get("summary","")}</div>' if data.get("summary") else ""}
  </div>
  <div class="layout">
    <div class="col">
      {f'<div class="sec-title">Experience</div>{exp_html}' if exp_html else ""}
      {f'<div class="sec-title" style="margin-top:16px">Education</div>{edu_html}' if edu_html else ""}
    </div>
    <div class="col">
      {f'<div class="sec-title">Projects</div>{proj_html}' if proj_html else ""}
      {f'<div class="sec-title" style="margin-top:16px">Skills</div><div style="margin-bottom:16px">{skills_html}</div>' if skills_html else ""}
      {f'<div class="sec-title" style="margin-top:16px">Certifications</div>{cert_html}' if cert_html else ""}
    </div>
  </div>
</div></body></html>'''

# ─── TEMPLATE 4: Corporate Navy ───────────────────────────────────
def template_corporate(data: dict) -> str:
    contact = ' | '.join(_build_contact_parts(data))
    exp_html = ''
    for job in data.get('experience', []):
        bullets = ''.join(f'<li>{b}</li>' for b in job.get('bullets', []) if b.strip())
        dur = job.get("start_date","") or job.get("duration","")
        end = f' – {job.get("end_date","Present")}' if job.get("start_date") else ""
        exp_html += f'''
        <div class="item">
          <div class="item-hd">
            <div class="ih-left"><div class="item-t">{job.get("title","")}</div>
            <div class="item-s">{job.get("company","")}{(", " + job.get("location","")) if job.get("location") else ""}</div></div>
            <div class="item-d">{dur}{end}</div>
          </div>
          <ul class="bl">{bullets}</ul>
        </div>'''

    proj_html = ''
    for p in data.get('projects', []):
        link_html = f'<div style="margin-top:6px"><strong>Link :</strong> <a class="pl" href="{p.get("link")}" target="_blank">{p.get("link","")}</a></div>' if p.get("link") else ""
        proj_html += f'''
        <div class="item">
          <div class="item-hd">
            <div class="ih-left"><div class="item-t" style="font-size:15.5px;font-weight:700;margin-bottom:4px;">{p.get("name","")}</div>
            <div class="item-s"><div class="i-sub tech"><strong>Technologies:</strong> {p.get("tech_stack","")}</div></div></div>
          </div>
          <p class="idesc">{p.get("description","")}</p>
          {link_html}
        </div>'''

    edu_html = _build_education_html(data.get('education', []))

    skills = data.get('skills', [])
    skills_html = ''
    if skills:
        skill_items = ''.join(f'<div class="skill-item">• {s}</div>' for s in skills)
        skills_html = f'<div class="section"><div class="skills-list">{skill_items}</div></div>'
    cert_html = ''
    for c in data.get('certifications', []):
        name = c.get('name','') if isinstance(c, dict) else str(c)
        if name.strip():
            cert_html += f'<div class="cert-row">🏅 {name}</div>'

    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<title>{data.get("name","Resume")}</title>
<link href="https://fonts.googleapis.com/css2?family=Libre+Baskerville:wght@400;700&family=Source+Sans+3:wght@400;500;600&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:"Source Sans 3",sans-serif;background:#f8fafc;color:#1e293b;font-size:13.5px}}
.page{{max-width:840px;margin:30px auto;background:#fff;box-shadow:0 4px 32px rgba(15,23,42,.1);overflow:visible;border-radius:6px}}
.hdr{{background:#0f172a;padding:38px 50px;color:#fff;border-bottom:4px solid #3b82f6}}
.h-name{{font-family:"Libre Baskerville",serif;font-size:40px;font-weight:700;letter-spacing:-.5px}}
.h-role{{font-size:14px;color:#94a3b8;margin-top:5px}}
.h-contact{{font-size:12.5px;color:#94a3b8;margin-top:12px}}
.h-contact a{{color:#60a5fa;text-decoration:none}}
.body{{padding:36px 50px}}
.sec{{margin-bottom:28px}}
.sec-title{{font-family:"Libre Baskerville",serif;font-size:15px;font-weight:700;color:#0f172a;
  padding-bottom:8px;border-bottom:2px solid #e2e8f0;margin-bottom:16px;
  display:flex;align-items:center;gap:10px}}
.sec-title::before{{content:"";display:block;width:4px;height:18px;background:#3b82f6;border-radius:2px}}
.item{{margin-bottom:16px;padding-bottom:14px;border-bottom:1px solid #f1f5f9}}
.item:last-child{{border-bottom:none}}
.item-hd{{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}}
.item-t{{font-size:14px;font-weight:600;color:#1e293b}}
.item-s{{font-size:12.5px;color:#64748b;margin-top:2px}}
.item-d{{font-size:12px;color:#3b82f6;font-weight:600;flex-shrink:0;background:#eff6ff;padding:2px 8px;border-radius:4px}}
.bl{{padding-left:16px;margin-top:8px}}
.bl li{{font-size:13px;margin-bottom:4px;color:#334155}}
.idesc{{font-size:13px;color:#334155;margin-top:6px}}
.edu-item {{
    margin-bottom: 22px;
    padding-bottom: 12px;
    border-bottom: 1px solid #eee;
}}
.edu-item:last-child {{
    border-bottom: none;
    margin-bottom: 0;
    padding-bottom: 0;
}}

.edu-top-row {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 4px;
}}

.edu-degree {{
    font-size: 15px;
    font-weight: 600;
    color: #1e1b2e;
}}

.edu-year {{
    font-size: 13px;
    font-weight: 500;
    color: #666;
    white-space: nowrap;
}}

.edu-bottom-row {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
}}

.edu-institution {{
    font-size: 13.5px;
    color: #555;
}}

.edu-gpa {{
    font-size: 13px;
    font-weight: 600;
    color: #111;
}}
.pl{{font-size:12px;color:#3b82f6;text-decoration:none;font-weight:600}}
.sk{{display:inline-block;margin:0 5px 5px 0;padding:4px 12px;background:#eff6ff;border:1px solid #bfdbfe;border-radius:4px;font-size:12.5px;color:#1d4ed8;font-weight:500}}
.cert{{display:inline-block;margin:0 6px 6px 0;font-size:12.5px;color:#334155;padding:3px 10px;border:1px solid #e2e8f0;border-radius:4px}}
</style></head><body>
<div class="page">
  <div class="hdr">
    <div class="h-name">{data.get("name","")}</div>
    <div class="h-role">{data.get("target_role","")}</div>
    <div class="h-contact">{contact}</div>
  </div>
  <div class="body">
    {f'<div class="sec"><div class="sec-title">Professional Summary</div><p style="font-size:13.5px;color:#334155;line-height:1.8">{data.get("summary","")}</p></div>' if data.get("summary") else ""}
    {f'<div class="sec"><div class="sec-title">Experience</div>{exp_html}</div>' if exp_html else ""}
    {f'<div class="sec"><div class="sec-title">Projects</div>{proj_html}</div>' if proj_html else ""}
    {f'<div class="sec"><div class="sec-title">Education</div>{edu_html}</div>' if edu_html else ""}
    {f'<div class="sec"><div class="sec-title">Skills</div><div style="margin-top:4px">{skills_html}</div></div>' if skills_html else ""}
    {f'<div class="sec"><div class="sec-title">Certifications</div><div style="margin-top:4px">{cert_html}</div></div>' if cert_html else ""}
  </div>
</div></body></html>'''


# ─── TEMPLATE 5: Creative Dark ────────────────────────────────────
def template_creative(data: dict) -> str:
    contact_parts = _build_contact_parts(data)
    contact = ''.join(f'<span class="ct">{p}</span>' for p in contact_parts)

    exp_html = ''
    for job in data.get('experience', []):
        bullets = ''.join(f'<li>{b}</li>' for b in job.get('bullets', []) if b.strip())
        dur = job.get("start_date","") or job.get("duration","")
        end = f' → {job.get("end_date","Present")}' if job.get("start_date") else ""
        exp_html += f'''
        <div class="xcard">
          <div class="xc-timeline"><div class="xc-dot"></div></div>
          <div class="xc-body">
            <div class="xc-top"><div class="xc-title">{job.get("title","")}</div><div class="xc-date">{dur}{end}</div></div>
            <div class="xc-sub">{job.get("company","")}{(" · " + job.get("location","")) if job.get("location") else ""}</div>
            <ul class="bl">{bullets}</ul>
          </div>
        </div>'''

    proj_html = ''
    for p in data.get('projects', []):
        link_html = f'<div style="margin-top:8px"><strong>Link :</strong> <a class="pc-link" href="{p.get("link")}" target="_blank">{p.get("link","")}</a></div>' if p.get("link") else ""
        proj_html += f'''
        <div class="proj-card">
          <div class="pc-top"><div class="pc-name" style="font-size:15.5px;font-weight:700;margin-bottom:4px;">{p.get("name","")}</div></div>
          <div class="pc-tech"><div class="i-sub tech"><strong>Technologies:</strong> {p.get("tech_stack","")}</div></div>
          <p class="pc-desc">{p.get("description","")}</p>
          {link_html}
        </div>'''

    skills_html = ''.join(f'<span class="sk">{s}</span>' for s in data.get('skills', []))

    edu_html = _build_education_html(data.get('education', []))

    cert_html = ''
    for c in data.get('certifications', []):
        name = c.get('name','') if isinstance(c, dict) else str(c)
        if name.strip(): cert_html += f'<div class="cert-item">⬡ {name}</div>'

    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<title>{data.get("name","Resume")}</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:"Space Grotesk",sans-serif;background:#09090b;color:#e4e4e7;font-size:13.5px;line-height:1.65}}
.page{{max-width:860px;margin:30px auto;background:#09090b;border:1px solid #27272a;overflow:visible;border-radius:8px}}
.hdr{{padding:48px 52px;background:linear-gradient(135deg,#18181b 0%,#09090b 100%);border-bottom:1px solid #27272a}}
.h-name{{font-family:"Space Mono",monospace;font-size:40px;font-weight:700;color:#f4f4f5;letter-spacing:-1.5px}}
.h-name span{{color:#a78bfa}}
.h-role{{font-size:13px;color:#71717a;margin-top:6px;font-family:"Space Mono",monospace;letter-spacing:1px}}
.ct-bar{{margin-top:16px;display:flex;flex-wrap:wrap;gap:8px 0}}
.ct{{font-size:12px;color:#a1a1aa;margin-right:16px}}
.ct a{{color:#a78bfa;text-decoration:none}}
.body{{display:grid;grid-template-columns:1fr 300px}}
.main-col{{padding:36px 40px;border-right:1px solid #27272a}}
.side-col{{padding:32px 28px}}
.sec-title{{font-family:"Space Mono",monospace;font-size:9px;font-weight:700;letter-spacing:3px;text-transform:uppercase;color:#a78bfa;margin:0 0 16px;padding-bottom:6px;border-bottom:1px solid #27272a}}
.xcard{{display:flex;gap:16px;margin-bottom:20px}}
.xc-timeline{{display:flex;flex-direction:column;align-items:center;width:16px;flex-shrink:0}}
.xc-dot{{width:10px;height:10px;border-radius:50%;background:#a78bfa;flex-shrink:0;margin-top:4px;box-shadow:0 0 8px rgba(167,139,250,.5)}}
.xc-body{{flex:1;border-bottom:1px solid #18181b;padding-bottom:14px}}
.xc-top{{display:flex;justify-content:space-between;align-items:baseline;gap:10px;margin-bottom:3px}}
.xc-title{{font-size:14px;font-weight:600;color:#f4f4f5}}
.xc-date{{font-size:11px;color:#a78bfa;font-family:"Space Mono",monospace;flex-shrink:0}}
.xc-sub{{font-size:12.5px;color:#71717a;margin-bottom:8px}}
.bl{{padding-left:14px}}
.edu-item {{
    margin-bottom: 22px;
    padding-bottom: 12px;
    border-bottom: 1px solid #eee;
}}
.edu-item:last-child {{
    border-bottom: none;
    margin-bottom: 0;
    padding-bottom: 0;
}}

.edu-top-row {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 4px;
}}

.edu-degree {{
    color:#f4f4f5
    font-size: 15px;
    font-weight: 600;
}}

.edu-year {{
    font-size:11px;color:#a78bfa;font-family:"Space Mono"
    font-weight: 500;
    white-space: nowrap;
}}

.edu-bottom-row {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
}}

.edu-institution {{
    font-size: 13px;
    color: #f4f4f5;
}}

.edu-gpa {{
    font-size:11px;color:#a78bfa;font-family:"Space Mono"
    font-weight: 600;
}}
.bl li{{font-size:12.5px;margin-bottom:5px;color:#a1a1aa}}
.proj-card{{background:#18181b;border:1px solid #27272a;border-radius:8px;padding:14px;margin-bottom:12px}}
.pc-top{{display:flex;justify-content:space-between;align-items:baseline}}
.pc-name{{font-size:14px;font-weight:600;color:#f4f4f5}}
.pc-tech{{font-size:11.5px;color:#a78bfa;margin:4px 0 6px;font-family:"Space Mono",monospace}}
.pc-desc{{font-size:12.5px;color:#71717a;line-height:1.6}}
.sk{{display:block;font-size:12.5px;color:#d4d4d8;padding:6px 10px;margin-bottom:6px;background:#18181b;border:1px solid #27272a;border-radius:6px}}
.edu-item{{margin-bottom:16px;padding-bottom:14px;border-bottom:1px solid #18181b}}
.cert-item{{font-size:12.5px;color:#71717a;padding:5px 0;border-bottom:1px solid #18181b}}
.summary-text{{font-size:13.5px;color:#a1a1aa;line-height:1.8;margin-bottom:24px;padding:14px;background:#18181b;border-left:3px solid #a78bfa;border-radius:0 6px 6px 0}}
@media print{{body{{background:#fff;color:#000}}.page{{border:none}}}}
</style></head><body>
<div class="page">
  <div class="hdr">
    <div class="h-name">{data.get("name","").split(" ")[0]}<span>{" ".join(data.get("name","").split(" ")[1:])}</span></div>
    <div class="h-role">{data.get("target_role","")}</div>
    <div class="ct-bar">{contact}</div>
  </div>
  <div class="body">
    <div class="main-col">
      {f'<div class="summary-text">{data.get("summary","")}</div>' if data.get("summary") else ""}
      {f'<div class="sec-title">Experience</div>{exp_html}' if exp_html else ""}
      {f'<div class="sec-title" style="margin-top:16px">Projects</div>{proj_html}' if proj_html else ""}
    </div>
    <div class="side-col">
      {f'<div class="sec-title">Skills</div><div style="margin-bottom:20px">{skills_html}</div>' if skills_html else ""}
      {f'<div class="sec-title">Education</div><div style="margin-bottom:20px">{edu_html}</div>' if edu_html else ""}
      {f'<div class="sec-title">Certifications</div>{cert_html}' if cert_html else ""}
    </div>
  </div>
</div></body></html>'''


# ─── TEMPLATE 6: Warm Academic ────────────────────────────────────
def template_academic(data: dict) -> str:
    contact = ' • '.join(_build_contact_parts(data))

    exp_html = ''
    for job in data.get('experience', []):
        bullets = ''.join(f'<li>{b}</li>' for b in job.get('bullets', []) if b.strip())
        dur = job.get("start_date","") or job.get("duration","")
        end = f' – {job.get("end_date","Present")}' if job.get("start_date") else ""
        exp_html += f'''
        <div class="item">
          <div class="i-row"><div><div class="i-title">{job.get("title","")}</div>
          <div class="i-sub">{job.get("company","")}{(", " + job.get("location","")) if job.get("location") else ""}</div></div>
          <div class="i-date">{dur}{end}</div></div>
          <ul class="bl">{bullets}</ul>
        </div>'''

    proj_html = ''
    for p in data.get('projects', []):
        link_html = f'<div style="margin-top:8px"><strong>Link :</strong> <a class="plink" href="{p.get("link")}" target="_blank">{p.get("link","")}</a></div>' if p.get("link") else ""
        proj_html += f'''
        <div class="item">
          <div class="i-row">
            <div>
              <div class="i-title" style="font-size:15.5px;font-weight:700;margin-bottom:4px;">{p.get("name","")}</div>
              <div class="i-sub tech"><div class="i-sub tech"><strong>Technologies:</strong> {p.get("tech_stack","")}</div></div>
            </div>
          </div>
          <p class="idesc">{p.get("description","")}</p>
          {link_html}
        </div>'''

    edu_html = _build_education_html(data.get('education', []))

    skills = data.get('skills', [])
    skills_html = ''
    if skills:
        skill_items = ''.join(f'<div class="skill-item">◆ {s}</div>' for s in skills)
        skills_html = f'<div class="section"><div class="skills-list">{skill_items}</div></div>'

    cert_html = ''
    for c in data.get('certifications', []):
        name = c.get('name','') if isinstance(c, dict) else str(c)
        if name.strip(): cert_html += f'<div class="cert-it">◆ {name}</div>'

    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<title>{data.get("name","Resume")}</title>
<link href="https://fonts.googleapis.com/css2?family=Crimson+Pro:wght@400;500;600;700&family=Jost:wght@400;500;600&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:"Jost",sans-serif;background:#fffbf5;color:#1c1309;font-size:13.5px;line-height:1.65}}
.page{{max-width:820px;margin:30px auto;background:#fff;box-shadow:0 4px 28px rgba(120,70,10,.1);border-top:5px solid #92400e}}
.hdr{{padding:40px 52px 32px;background:#fffbf5;border-bottom:1px solid #fde68a}}
.h-name{{font-family:"Crimson Pro",serif;font-size:50px;font-weight:700;color:#78350f;letter-spacing:-1px;line-height:1}}
.h-role{{font-size:14px;color:#92400e;margin-top:5px;font-weight:500}}
.h-contact{{font-size:12.5px;color:#6b5020;margin-top:12px}}
.h-contact a{{color:#92400e;text-decoration:none}}
.body{{padding:36px 52px}}
.sec-title{{font-family:"Crimson Pro",serif;font-size:18px;font-weight:700;color:#78350f;margin:0 0 12px;letter-spacing:-.3px;
  border-bottom:1.5px solid #fde68a;padding-bottom:4px}}
.sec{{margin-bottom:28px}}
.item{{margin-bottom:16px;padding-bottom:14px;border-bottom:1px dotted #fde68a}}
.item:last-child{{border-bottom:none}}
.i-row{{display:flex;justify-content:space-between;align-items:baseline;gap:12px;margin-bottom:4px}}
.i-title{{font-family:"Crimson Pro",serif;font-size:16px;font-weight:600;color:#1c1309}}
.i-sub{{font-size:12.5px;color:#92400e}}
.i-sub.tech{{color:#b45309;font-style:italic;font-weight:500}}
.i-date{{font-size:12px;color:#a16207;font-weight:500;flex-shrink:0;background:#fef3c7;padding:2px 8px;border-radius:3px}}
.bl{{padding-left:16px;margin-top:6px}}
.edu-item {{
    margin-bottom: 22px;
    padding-bottom: 12px;
    border-bottom: 1px solid #eee;
}}
.edu-item:last-child {{
    border-bottom: none;
    margin-bottom: 0;
    padding-bottom: 0;
}}

.edu-top-row {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 4px;
}}

.edu-degree {{
    font-size: 15px;
    font-weight: 600;
    color: #1e1b2e;
}}

.edu-year {{
    font-size: 13px;
    font-weight: 500;
    color: #666;
    white-space: nowrap;
}}

.edu-bottom-row {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
}}

.edu-institution {{
    font-size: 13.5px;
    color: #555;
}}

.edu-gpa {{
    font-size: 13px;
    font-weight: 600;
    color: #111;
}}
.bl li{{margin-bottom:4px;font-size:13px;color:#292524}}
.idesc{{font-size:13.2px;color:#292524;margin-top:8px;line-height:1.65}}
.plink{{font-size:12.5px;color:#92400e;text-decoration:underline;flex-shrink:0}}
.skills-txt{{font-size:13.5px;color:#292524;line-height:1.9}}
.cert-it{{font-size:13px;color:#292524;padding:4px 0;border-bottom:1px dotted #fde68a}}
</style></head><body>
<div class="page">
  <div class="hdr">
    <div class="h-name">{data.get("name","")}</div>
    <div class="h-role">{data.get("target_role","")}</div>
    <div class="h-contact">{contact}</div>
  </div>
  <div class="body">
    {f'<div class="sec"><div class="sec-title">Objective</div><p style="font-size:13.5px;color:#292524;line-height:1.8">{data.get("summary","")}</p></div>' if data.get("summary") else ""}
    {f'<div class="sec"><div class="sec-title">Experience</div>{exp_html}</div>' if exp_html else ""}
    {f'<div class="sec"><div class="sec-title">Projects</div>{proj_html}</div>' if proj_html else ""}
    {f'<div class="sec"><div class="sec-title">Education</div>{edu_html}</div>' if edu_html else ""}
    {f'<div class="sec"><div class="sec-title">Skills</div><div class="skills-txt">{skills_html}</div></div>' if skills_html else ""}
    {f'<div class="sec"><div class="sec-title">Certifications</div>{cert_html}</div>' if cert_html else ""}
  </div>
</div></body></html>'''


# ─── TEMPLATE 7: Rose Gold ────────────────────────────
def template_rosegold(data: dict) -> str:
    contact = ' &nbsp;|&nbsp; '.join(_build_contact_parts(data))
    skills_html = ''.join(f'<span class="sk-pill">{s}</span>' for s in data.get('skills', []))
    exp_html = ''
    for job in data.get('experience', []):
        bullets = ''.join(f'<li>{b}</li>' for b in job.get('bullets', []) if b.strip())
        dur = job.get("start_date","") or job.get("duration","")
        end = f' — {job.get("end_date","Present")}' if job.get("start_date") else ""
        exp_html += f'''<div class="item">
          <div class="item-row">
            <div><div class="item-title">{job.get("title","")}</div>
            <div class="item-sub">{job.get("company","")}{(" · " + job.get("location","")) if job.get("location") else ""}</div></div>
            <div class="item-date">{dur}{end}</div>
          </div><ul class="blist">{bullets}</ul></div>'''
    proj_html = ''
    for p in data.get('projects', []):
        link_html = f'<div style="margin-top:8px"><strong>Link :</strong> <a href="{p.get("link")}" target="_blank" style="color:inherit">{p.get("link","")}</a></div>' if p.get("link") else ""
        proj_html += f'''
        <div class="item">
          <div class="item-row">
            <div><div class="item-title" style="font-size:15.5px;font-weight:700;margin-bottom:4px;">{p.get("name","")}</div>
            <div class="item-sub"><div class="i-sub tech"><strong>Technologies:</strong> {p.get("tech_stack","")}</div></div></div>
          </div>
          <p class="item-desc">{p.get("description","")}</p>
          {link_html}
        </div>'''

    edu_html = _build_education_html(data.get('education', []))
       
    cert_html = ''.join(f'<div class="cert-row">🌸 {(c.get("name","") if isinstance(c,dict) else str(c))}</div>'
                        for c in data.get('certifications',[]) if (c.get("name","") if isinstance(c,dict) else str(c)).strip())
    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<title>{data.get("name","Resume")}</title>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;600;700&family=Nunito:wght@400;500;600&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:"Nunito",sans-serif;background:#fdf2f8;color:#1a0a0f;font-size:13.5px;line-height:1.65}}
.page{{max-width:850px;margin:30px auto;background:#fff;box-shadow:0 8px 40px rgba(159,18,57,.12);border-radius:4px;overflow:visible}}
.hdr{{background:linear-gradient(135deg,#881337 0%,#9f1239 40%,#be185d 80%,#db2777 100%);padding:44px 52px 36px;color:#fff}}
.hdr-name{{font-family:"Cormorant Garamond",serif;font-size:50px;font-weight:700;letter-spacing:-0.5px;line-height:1}}
.hdr-role{{font-size:15px;font-weight:500;margin-top:6px;opacity:.85;letter-spacing:.5px}}
.hdr-contact{{margin-top:18px;font-size:12.5px;opacity:.85;display:flex;flex-wrap:wrap;gap:8px 16px}}
.hdr-contact a{{color:#fce7f3;text-decoration:none}}
.body{{display:grid;grid-template-columns:210px 1fr;min-height:600px}}
.sidebar{{background:#fff0f6;padding:32px 22px;border-right:1px solid #fbcfe8}}
.main{{padding:32px 40px}}
.sec-title{{font-size:10px;font-weight:700;letter-spacing:2.5px;text-transform:uppercase;color:#be185d;margin:0 0 14px;padding-bottom:6px;border-bottom:2px solid #fbcfe8}}
.sidebar .sec-title{{color:#9f1239;border-color:#f9a8d4}}
.sk-pill{{display:block;font-size:12px;padding:5px 10px;margin-bottom:6px;background:#fce7f3;border-radius:6px;color:#9f1239;font-weight:500}}
.item{{margin-bottom:22px}}
.edu-item {{
    margin-bottom: 22px;
    padding-bottom: 12px;
    border-bottom: 1px solid #eee;
}}
.edu-item:last-child {{
    border-bottom: none;
    margin-bottom: 0;
    padding-bottom: 0;
}}

.edu-top-row {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 4px;
}}

.edu-degree {{
    font-size: 15px;
    font-weight: 600;
    color: #1e1b2e;
}}

.edu-year {{
    font-size: 13px;
    font-weight: 500;
    color: #666;
    white-space: nowrap;
}}

.edu-bottom-row {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
}}

.edu-institution {{
    font-size: 13.5px;
    color: #555;
}}

.edu-gpa {{
    font-size: 13px;
    font-weight: 600;
    color: #111;
}}
.item-row{{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:4px}}
.item-title{{font-size:14.5px;font-weight:600;color:#1a0a0f}}
.item-sub{{font-size:12.5px;color:#6b7280;margin-top:2px}}
.item-date{{font-size:11.5px;color:#be185d;font-weight:600;white-space:nowrap;flex-shrink:0}}
.blist{{padding-left:16px;margin-top:8px}}
.blist li{{margin-bottom:5px;font-size:13px;color:#374151}}
.item-desc{{font-size:13px;color:#374151;margin-top:6px}}
.gpa{{font-size:12px;color:#6b7280;margin-top:4px}}
.cert-row{{font-size:13px;color:#374151;padding:4px 0;border-bottom:1px dashed #fbcfe8}}
.sidebar-sec{{margin-bottom:28px}}
@media print{{body{{background:#fff}}.page{{box-shadow:none;margin:0}}}}
</style></head><body>
<div class="page">
  <div class="hdr">
    <div class="hdr-name">{data.get("name","")}</div>
    <div class="hdr-role">{data.get("target_role","")}</div>
    <div class="hdr-contact">{contact}</div>
  </div>
  <div class="body">
    <div class="sidebar">
      {f'<div class="sidebar-sec"><div class="sec-title">Skills</div>{skills_html}</div>' if skills_html else ""}
      {f'<div class="sidebar-sec"><div class="sec-title">Languages</div><div style="font-size:12.5px;color:#374151;line-height:1.8">{data.get("languages","")}</div></div>' if data.get("languages") else ""}
      {f'<div class="sidebar-sec"><div class="sec-title">Tools</div><div style="font-size:12.5px;color:#374151;line-height:1.8">{data.get("tools","")}</div></div>' if data.get("tools") else ""}
    </div>
    <div class="main">
      {f'<div style="margin-bottom:28px"><div class="sec-title">Objective</div><p style="font-size:13.5px;color:#374151;line-height:1.75">{data.get("summary","")}</p></div>' if data.get("summary") else ""}
      {f'<div style="margin-bottom:28px"><div class="sec-title">Experience</div>{exp_html}</div>' if exp_html else ""}
      {f'<div style="margin-bottom:28px"><div class="sec-title">Projects</div>{proj_html}</div>' if proj_html else ""}
      {f'<div style="margin-bottom:28px"><div class="sec-title">Education</div>{edu_html}</div>' if edu_html else ""}
      {f'<div style="margin-bottom:28px"><div class="sec-title">Certifications</div>{cert_html}</div>' if cert_html else ""}
    </div>
  </div>
</div></body></html>'''


# ─── TEMPLATE 8: Forest Green  ───────────────────

def template_forest(data: dict) -> str:
    contact = ' · '.join(_build_contact_parts(data))
    skills = data.get('skills', [])
    skills_html = ''
    if skills:
        skill_items = ''.join(f'<div class="skill-item">• {s}</div>' for s in skills)
        skills_html = f'<div class="section"><div class="skills-list">{skill_items}</div></div>'
    exp_html = ''
    for job in data.get('experience', []):
        bullets = ''.join(f'<li>{b}</li>' for b in job.get('bullets', []) if b.strip())
        dur = job.get("start_date","") or job.get("duration","")
        end = f' – {job.get("end_date","Present")}' if job.get("start_date") else ""
        exp_html += f'''<div class="item">
          <div class="i-head"><span class="i-title">{job.get("title","")}</span><span class="i-date">{dur}{end}</span></div>
          <div class="i-sub">{job.get("company","")}{(", " + job.get("location","")) if job.get("location") else ""}</div>
          <ul class="blist">{bullets}</ul></div>'''
    proj_html = ''
    for p in data.get('projects', []):
        link_html = f'<div style="margin-top:8px"><strong>Link :</strong> <a href="{p.get("link")}" target="_blank" style="color:inherit">{p.get("link","")}</a></div>' if p.get("link") else ""
        proj_html += f'''
        <div class="item">
          <div class="item-row">
            <div><div class="item-title"><strong>{p.get("name","")}</strong></div>
            <div class="item-sub"><div class="i-sub tech"><strong>Technologies:</strong> {p.get("tech_stack","")}</div></div></div>
          </div>
          <p class="item-desc">{p.get("description","")}</p>
          {link_html}
        </div>'''

    edu_html = _build_education_html(data.get('education', []))    
    cert_items = ''.join(f'<div class="cert-item">• {(c.get("name","") if isinstance(c, dict) else str(c))}</div>'
                        for c in data.get('certifications', []) if (c.get("name","") if isinstance(c, dict) else str(c)).strip())
    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<title>{data.get("name","Resume")}</title>
<link href="https://fonts.googleapis.com/css2?family=Merriweather:wght@400;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:"Inter",sans-serif;background:#f0fdf4;color:#14532d;font-size:13.5px;line-height:1.65}}
.page{{max-width:820px;margin:30px auto;background:#fff;box-shadow:0 4px 32px rgba(20,83,45,.12);border-top:5px solid #16a34a;overflow:visible}}
.hdr{{background:linear-gradient(135deg,#14532d,#166534,#15803d);padding:42px 52px 34px;color:#fff}}
.hdr-name{{font-family:"Merriweather",serif;font-size:42px;font-weight:700;letter-spacing:-0.5px;line-height:1.1}}
.hdr-role{{font-size:14px;opacity:.85;margin-top:8px;letter-spacing:.3px}}
.hdr-contact{{margin-top:16px;font-size:12.5px;opacity:.8;display:flex;flex-wrap:wrap;gap:8px 18px}}
.hdr-contact a{{color:#bbf7d0;text-decoration:none}}
.body{{padding:36px 52px}}
.sec-title{{font-family:"Merriweather",serif;font-size:13px;font-weight:700;color:#14532d;margin:0 0 14px;padding-bottom:6px;border-bottom:2px solid #bbf7d0;letter-spacing:.3px}}
.sec{{margin-bottom:28px}}
.item{{margin-bottom:18px;padding-bottom:14px;border-bottom:1px dotted #bbf7d0}}
.item:last-child{{border-bottom:none}}
.i-head{{display:flex;justify-content:space-between;align-items:baseline;gap:10px;margin-bottom:3px}}
.i-title{{font-size:14px;font-weight:600;color:#14532d}}
.i-date{{font-size:11.5px;color:#16a34a;font-weight:600;flex-shrink:0;background:#dcfce7;padding:2px 8px;border-radius:4px}}
.i-sub{{font-size:12.5px;color:#4b7a5a;margin:2px 0 6px}}
.blist{{padding-left:15px}}
.edu-item {{
    margin-bottom: 22px;
    padding-bottom: 12px;
    border-bottom: 1px solid #eee;
}}
.edu-item:last-child {{
    border-bottom: none;
    margin-bottom: 0;
    padding-bottom: 0;
}}

.edu-top-row {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 4px;
}}

.edu-degree {{
    font-size: 15px;
    font-weight: 600;
    color: #1e1b2e;
}}

.edu-year {{
    font-size: 13px;
    font-weight: 500;
    color: #666;
    white-space: nowrap;
}}

.edu-bottom-row {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
}}

.edu-institution {{
    font-size: 13.5px;
    color: #555;
}}

.edu-gpa {{
    font-size: 13px;
    font-weight: 600;
    color: #111;
}}
.blist li{{margin-bottom:4px;font-size:13px;color:#1c3829}}
.cert-chip{{display:inline-block;margin:0 8px 8px 0;font-size:12px;color:#14532d;border:1px solid #86efac;padding:3px 10px;border-radius:20px;background:#dcfce7}}
@media print{{body{{background:#fff}}.page{{border-top:none;box-shadow:none;margin:0}}}}
</style></head><body>
<div class="page">
  <div class="hdr">
    <div class="hdr-name">{data.get("name","")}</div>
    <div class="hdr-role">{data.get("target_role","")}</div>
    <div class="hdr-contact">{contact}</div>
  </div>
  <div class="body">
    {f'<div class="sec"><div class="sec-title">Profile</div><p style="font-size:13.5px;color:#1c3829;line-height:1.8">{data.get("summary","")}</p></div>' if data.get("summary") else ""}
    {f'<div class="sec"><div class="sec-title">Experience</div>{exp_html}</div>' if exp_html else ""}
    {f'<div class="sec"><div class="sec-title">Projects</div>{proj_html}</div>' if proj_html else ""}
    {f'<div class="sec"><div class="sec-title">Education</div>{edu_html}</div>' if edu_html else ""}
    {f'<div class="sec"><div class="sec-title">Skills</div><div style="font-size:13px;color:#1c3829;line-height:1.9">{skills_html}</div></div>' if skills_html else ""}
    {f'<div class="sec"><div class="sec-title">Certifications</div><div style="margin-top:4px">{cert_items}</div></div>' if cert_items else ""}
  </div>
</div></body></html>'''

# ─── TEMPLATE 9: Slate Pro ────────────────────────────
def template_slatepro(data: dict) -> str:
    contact_parts = _build_contact_parts(data)
    contact = ''.join(f'<div class="c-item">{p}</div>' for p in contact_parts)
    skills = data.get('skills', [])
    skills_html = ''
    if skills:
        skill_items = ''.join(f'<div class="skill-item">• {s}</div>' for s in skills)
        skills_html = f'<div class="section"><div class="skills-list">{skill_items}</div></div>'
    exp_html = ''
    for job in data.get('experience', []):
        bullets = ''.join(f'<li>{b}</li>' for b in job.get('bullets', []) if b.strip())
        dur = job.get("start_date","") or job.get("duration","")
        end = f' – {job.get("end_date","Present")}' if job.get("start_date") else ""
        exp_html += f'''<div class="card">
          <div class="card-left"><div class="card-dot"></div></div>
          <div class="card-body">
            <div class="card-top">
              <div><div class="card-title">{job.get("title","")}</div>
              <div class="card-sub">{job.get("company","")}{(" · " + job.get("location","")) if job.get("location") else ""}</div></div>
              <div class="card-date">{dur}{end}</div>
            </div>
            <ul class="blist">{bullets}</ul>
          </div></div>'''
    proj_html = ''
    for p in data.get('projects', []):
        link_html = f'<div style="margin-top:8px"><strong>Link :</strong> <a href="{p.get("link")}" target="_blank" style="color:inherit">{p.get("link","")}</a></div>' if p.get("link") else ""
        proj_html += f'''
        <div class="item">
          <div class="item-row">
            <div><div class="item-title" style="font-size:15.5px;font-weight:700;margin-bottom:4px;">{p.get("name","")}</div>
            <div class="item-sub"><div class="i-sub tech"><strong>Technologies:</strong> {p.get("tech_stack","")}</div></div></div>
          </div>
          <p class="item-desc">{p.get("description","")}</p>
          {link_html}
        </div>'''
    edu_html = ''
    for e in data.get('education', []):
        edu_html += f'''<div class="edu-row">
          <div class="edu-left">
            <div class="card-title">{e.get("degree","")}</div>
            <div class="card-sub">{e.get("institution","")}</div>
          </div>
          <div class="card-date">{e.get("graduation_year","")}
          <div class="card-sub">{(f'{e.get("gpa")}') if e.get("gpa") else ""}</div></div>
          </div>'''
    cert_html = ''
    for c in data.get('certifications', []):
        name = c.get('name','') if isinstance(c, dict) else str(c)
        if name.strip():
            cert_html += f'<div class="cert-row">🏅 {name}</div>'
    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<title>{data.get("name","Resume")}</title>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:"Outfit",sans-serif;background:#f8fafc;color:#0f172a;font-size:13.5px;line-height:1.65}}
.page{{max-width:860px;margin:30px auto;background:#fff;box-shadow:0 4px 32px rgba(15,23,42,.1);overflow:visible}}
.hdr{{background:linear-gradient(135deg,#1e293b 0%,#334155 100%);padding:0;color:#fff;position:relative}}
.hdr-accent{{height:4px;background:linear-gradient(90deg,#6366f1,#8b5cf6,#a78bfa)}}
.hdr-inner{{padding:36px 50px 32px}}
.hdr-name{{font-size:44px;font-weight:800;letter-spacing:-1px;line-height:1}}
.hdr-role{{font-size:14px;color:#94a3b8;margin-top:5px;letter-spacing:.3px}}
.hdr-contact{{margin-top:14px;font-size:12.5px;color:#94a3b8;display:flex;flex-wrap:wrap;gap:6px 20px}}
.hdr-contact a{{color:#a5b4fc;text-decoration:none}}
.body{{padding:36px 50px}}
.sec{{margin-bottom:28px}}
.sec-title{{font-size:12px;font-weight:700;letter-spacing:2.5px;text-transform:uppercase;color:#6366f1;margin:0 0 16px;padding-bottom:6px;border-bottom:1px solid #e2e8f0;display:flex;align-items:center;gap:8px}}
.sec-title::before{{content:"";width:16px;height:3px;background:linear-gradient(90deg,#6366f1,#a78bfa);border-radius:2px;flex-shrink:0}}
.card{{display:flex;gap:14px;margin-bottom:18px}}
.card-left{{display:flex;flex-direction:column;align-items:center;width:14px;flex-shrink:0;padding-top:4px}}
.card-dot{{width:10px;height:10px;border-radius:50%;background:#6366f1;box-shadow:0 0 0 3px rgba(99,102,241,.15);flex-shrink:0}}
.card-body{{flex:1;padding-bottom:14px;border-bottom:1px solid #f1f5f9}}
.card-top{{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:6px}}
.card-title{{font-size:14px;font-weight:600;color:#0f172a}}
.card-sub{{font-size:12.5px;color:#64748b;margin-top:2px}}
.card-date{{font-size:11.5px;color:#6366f1;font-weight:600;white-space:nowrap;flex-shrink:0;background:#eef2ff;padding:2px 8px;border-radius:4px}}
.blist{{padding-left:14px;margin-top:6px}}
.blist li{{font-size:13px;margin-bottom:4px;color:#334155}}
.item{{margin-bottom:18px}}
.item-row{{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:4px}}
.item-title{{font-size:14px;font-weight:600;color:#0f172a}}
.item-sub{{font-size:12.5px;color:#64748b;margin-top:2px}}
.item-desc{{font-size:12.5px;color:#475569}}
.edu-row{{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:14px;padding:12px;background:#f8fafc;border-radius:8px;border-left:3px solid #6366f1}}
.edu-left{{}}
.sk{{display:inline-block;margin:0 5px 5px 0;padding:4px 12px;background:#eef2ff;border:1px solid #c7d2fe;border-radius:4px;font-size:12.5px;color:#4338ca;font-weight:500}}
.cert{{display:inline-block;margin:0 6px 6px 0;font-size:12px;color:#334155;padding:3px 10px;border:1px solid #e2e8f0;border-radius:20px}}
@media print{{body{{background:#fff}}.page{{box-shadow:none;margin:0}}}}
</style></head><body>
<div class="page">
  <div class="hdr">
    <div class="hdr-accent"></div>
    <div class="hdr-inner">
      <div class="hdr-name">{data.get("name","")}</div>
      <div class="hdr-role">{data.get("target_role","")}</div>
      <div class="hdr-contact">{contact}</div>
    </div>
  </div>
  <div class="body">
    {f'<div class="sec"><div class="sec-title">Summary</div><p style="font-size:13.5px;color:#334155;line-height:1.8">{data.get("summary","")}</p></div>' if data.get("summary") else ""}
    {f'<div class="sec"><div class="sec-title">Experience</div>{exp_html}</div>' if exp_html else ""}
    {f'<div class="sec"><div class="sec-title">Projects</div>{proj_html}</div>' if proj_html else ""}
    {f'<div class="sec"><div class="sec-title">Education</div>{edu_html}</div>' if edu_html else ""}
    {f'<div class="sec"><div class="sec-title">Skills</div><div style="margin-top:4px">{skills_html}</div></div>' if skills_html else ""}
    {f'<div class="sec"><div class="sec-title">Certifications</div><div style="margin-top:4px">{cert_html}</div></div>' if cert_html else ""}
  </div>
</div></body></html>'''

# ─── TEMPLATE 10: Cyberpunk ────────────────────────────
def template_cyber(data: dict) -> str:
    contact_parts = _build_contact_parts(data)
    contact = ''.join(f'<span class="ct">{p}</span>' for p in contact_parts)
    skills_html = ''.join(f'<div class="sk">{s}</div>' for s in data.get('skills', []))
    exp_html = ''
    for job in data.get('experience', []):
        bullets = ''.join(f'<li>{b}</li>' for b in job.get('bullets', []) if b.strip())
        dur = job.get("start_date", "") or job.get("duration", "")
        end = f' — {job.get("end_date","Present")}' if job.get("start_date") else ""
        exp_html += f'''
        <div class="item">
          <div class="item-top">
            <div class="item-title">{job.get("title","")}</div>
            <div class="item-date">{dur}{end}</div>
          </div>
          <div class="item-sub">{job.get("company","")}{(" . " + job.get("location","")) if job.get("location") else ""}</div>
          <ul class="bl">{bullets}</ul>
        </div>'''
    proj_html = ''
    for p in data.get('projects', []):
        link_html = f'<div style="margin-top:8px"><strong>Link :</strong> <a class="proj-link" href="{p.get("link")}" target="_blank">{p.get("link","")}</a></div>' if p.get("link") else ""
        proj_html += f'''
        <div class="item">
          <div class="item-top">
            <div class="item-title" style="font-size:15.5px;font-weight:700;margin-bottom:4px;">{p.get("name","")}</div>
          </div>
          <div class="item-sub"><div class="i-sub tech"><strong>Technologies:</strong> {p.get("tech_stack","")}</div></div>
          <p class="item-desc">{p.get("description","")}</p>
          {link_html}
        </div>'''
    edu_html = _build_education_html(data.get('education', []))
    cert_html = ''.join(f'<div class="cert-item">• {(c.get("name","") if isinstance(c, dict) else str(c))}</div>'
                        for c in data.get('certifications', []) if (c.get("name","") if isinstance(c, dict) else str(c)).strip())
    return f'''<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>{data.get("name","Resume")}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Playfair+Display:wght@600;700&display=swap" rel="stylesheet">
<style>
    * {{ margin:0; padding:0; box-sizing:border-box; }}
    body {{ font-family: 'Inter', sans-serif; background: #f8f9fa; color: #1f2937; font-size: 14px; line-height: 1.65; }}
    .page {{ max-width: 860px; margin: 30px auto; background: #ffffff; box-shadow: 0 10px 40px rgba(0,0,0,0.08); border-radius: 8px; overflow: visible; }}
    .hdr {{ background: #1e2937; color: white; padding: 48px 55px; }}
    .hdr-name {{ font-family: 'Playfair Display', serif; font-size: 42px; font-weight: 700; letter-spacing: -1px; }}
    .hdr-role {{ font-size: 15.5px; color: #94a3b8; margin-top: 8px; }}
    .ct-bar {{ margin-top: 18px; display: flex; flex-wrap: wrap; gap: 12px 0; font-size: 13px; }}
    .ct {{ margin-right: 22px; }}
    .ct a {{ color: #60a5fa; text-decoration: none; }}
    .body {{ display: grid; grid-template-columns: 1fr 300px; }}
    .main-col {{ padding: 45px 50px; }}
    .side-col {{ padding: 45px 35px; background: #f8fafc; border-left: 1px solid #e2e8f0; }}
    .sec-title {{ font-size: 11.5px; font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase; color: #64748b; margin-bottom: 16px; padding-bottom: 8px; border-bottom: 1px solid #e2e8f0; }}
    .item {{ margin-bottom: 26px; }}
    .edu-item {{
    margin-bottom: 22px;
    padding-bottom: 12px;
    border-bottom: 1px solid #eee;
}}
.edu-item:last-child {{
    border-bottom: none;
    margin-bottom: 0;
    padding-bottom: 0;
}}

.edu-top-row {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 4px;
}}

.edu-degree {{
    font-size: 15px;
    font-weight: 600;
    color: #1e1b2e;
}}

.edu-year {{
    font-size: 13px;
    font-weight: 500;
    color: #666;
    white-space: nowrap;
}}

.edu-bottom-row {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
}}

.edu-institution {{
    font-size: 13.5px;
    color: #555;
}}

.edu-gpa {{
    font-size: 13px;
    font-weight: 600;
    color: #111;
}}
    .item-top {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 4px; }}
    .item-title {{ font-size: 15px; font-weight: 600; color: #1e2937; }}
    .item-date {{ font-size: 13px; color: #64748b; }}
    .item-sub {{ font-size: 13.5px; color: #475569; margin-bottom: 8px; }}
    .bl {{ padding-left: 20px; }}
    .bl li {{ margin-bottom: 6px; color: #334155; }}
    .proj-link {{ color: #2563eb; text-decoration: none; }}
    .item-desc {{ margin-top: 8px; color: #475569; line-height: 1.6; }}
    .sk {{ display: block; background: #f1f5f9; padding: 8px 14px; margin-bottom: 8px; border-radius: 6px; font-size: 13.2px; color: #334155; }}
    .cert-item {{ padding: 7px 0; color: #475569; border-bottom: 1px solid #f1f5f9; }}
    .summary-text {{ font-size: 14.5px; color: #374151; line-height: 1.75; margin-bottom: 30px; }}
    @media print {{ body {{ background: white; }} .page {{ box-shadow: none; margin: 0; border-radius: 0; }} }}
</style></head><body>
<div class="page">
  <div class="hdr">
    <div class="hdr-name">{data.get("name","")}</div>
    <div class="hdr-role">{data.get("target_role","")}</div>
    <div class="ct-bar">{contact}</div>
  </div>
  <div class="body">
    <div class="main-col">
      {f'<div class="summary-text">{data.get("summary","")}</div>' if data.get("summary") else ""}
      {f'<div class="sec-title">Experience</div>{exp_html}' if exp_html else ""}
      {f'<div class="sec-title" style="margin-top:30px">Projects</div>{proj_html}' if proj_html else ""}
      {f'<div class="sec-title" style="margin-top:30px">Education</div>{edu_html}' if edu_html else ""}
    </div>
    <div class="side-col">
      {f'<div class="sec-title">Skills</div><div style="margin-bottom:24px">{skills_html}</div>' if skills_html else ""}
      {f'<div class="sec-title">Certifications</div>{cert_html}' if cert_html else ""}
    </div>
  </div>
</div></body></html>'''

# ─── TEMPLATE 11: Classic ────────────────────────────
def template_classic(data: dict) -> str:
    contact_parts = []
    if data.get('location'): contact_parts.append(f'📍 {data["location"]}')
    if data.get('phone'):    contact_parts.append(f'📞 {data["phone"]}')
    if data.get('email'):    contact_parts.append(f'✉ {data["email"]}')
    if data.get('linkedin'): contact_parts.append(f'<a href="{data["linkedin"]}" target="_blank">LinkedIn</a>')
    if data.get('github'):   contact_parts.append(f'<a href="{data["github"]}" target="_blank">GitHub</a>')
    contact = ' &nbsp;·&nbsp; '.join(contact_parts)
    exp_html = ''
    for job in data.get('experience', []):
        bullets = ''.join(f'<li>{b}</li>' for b in job.get('bullets', []) if b.strip())
        dur = job.get("start_date", "") or job.get("duration", "")
        end = f' – {job.get("end_date","Present")}' if job.get("start_date") else ""
        loc = f'<span class="loc"> · {job.get("location","")}</span>' if job.get("location") else ""
        exp_html += f'''
        <div class="item">
          <div class="item-row">
            <div class="item-left">
              <span class="item-title">{job.get("title","")}</span>
              <span class="item-org"> · {job.get("company","")}</span>
              {loc}
            </div>
            <span class="item-date">{dur}{end}</span>
          </div>
          {'<ul>' + bullets + '</ul>' if bullets else ""}
        </div>'''
    proj_html = ''
    for p in data.get('projects', []):
        link_html = f'<div class="proj-link"><strong>Link:</strong> <a href="{p.get("link")}" target="_blank">{p.get("link","")}</a></div>' if p.get("link") else ""
        proj_html += f'''
        <div class="item">
          <div class="item-row">
            <span class="item-title">{p.get("name","")}</span>
          </div>
          <div class="tech-line"><strong>Technologies:</strong> {p.get("tech_stack","")}</div>
          <p class="item-desc">{p.get("description","")}</p>
          {link_html}
        </div>'''
    edu_html = _build_education_html(data.get('education', []))
    skills_html = ''
    if data.get('skills'):
        skill_items = ''.join(f'<div class="skill-item">• {s}</div>' for s in data.get('skills', []))
        skills_html = f'<div class="section"><div class="skills-list">{skill_items}</div></div>'
    cert_html = ''.join(
        f'<div class="cert-row">✔ {(c.get("name","") if isinstance(c, dict) else str(c))}</div>'
        for c in data.get('certifications', [])
        if (c.get("name","") if isinstance(c, dict) else str(c)).strip()
    )
    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<title>{data.get("name","Resume")}</title>
<link href="https://fonts.googleapis.com/css2?family=Lato:wght@400;700;900&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:"Lato",Arial,sans-serif;background:#fff;color:#1a1a1a;font-size:13px;line-height:1.65}}
.page{{width:794px;margin:0 auto;padding:44px 52px 40px;overflow:visible;box-shadow:0 4px 32px rgba(26,26,26,.1)}}
.hdr{{text-align:center;margin-bottom:22px;padding-bottom:18px;border-bottom:2.5px solid #1a1a1a}}
.hdr-name{{font-size:34px;font-weight:900;letter-spacing:0.5px;color:#1a1a1a;line-height:1.1;margin-bottom:5px}}
.hdr-role{{font-size:14.5px;color:#444;font-weight:400;margin-bottom:10px}}
.hdr-contact{{font-size:12px;color:#555;display:flex;flex-wrap:wrap;justify-content:center;gap:4px 16px}}
.hdr-contact a{{color:#1a1a1a;text-decoration:none;border-bottom:1px solid #ccc}}
.sec-title{{font-size:12px;font-weight:700;letter-spacing:2.5px;text-transform:uppercase;color:#1a1a1a;margin:20px 0 10px;display:flex;align-items:center;gap:10px;break-after:avoid;page-break-after:avoid}}
.sec-title::after{{content:"";flex:1;height:1.5px;background:#1a1a1a}}
.sec{{break-inside:avoid;page-break-inside:avoid}}
.item{{margin-bottom:16px;padding-bottom:14px;border-bottom:1px solid #e8e8e8;break-inside:avoid;page-break-inside:avoid}}
.item:last-child{{border-bottom:none;padding-bottom:0}}
.item-row{{display:flex;justify-content:space-between;align-items:baseline;gap:12px;margin-bottom:3px;overflow:hidden}}
.item-left{{flex:1;min-width:0;overflow:hidden}}
.item-title{{font-size:13.5px;font-weight:700;color:#1a1a1a}}
.item-org{{font-size:13px;color:#444;font-weight:400}}
.loc{{font-size:12px;color:#777}}
.item-date{{font-size:11.5px;color:#555;font-weight:600;white-space:nowrap;flex-shrink:0;background:#f3f3f3;padding:2px 8px;border-radius:4px}}
ul{{padding-left:18px;margin-top:6px}}
li{{margin-bottom:4px;font-size:12.5px;color:#333;line-height:1.55}}
.tech-line{{font-size:12px;color:#555;margin:4px 0 5px}}
.tech-line strong{{color:#1a1a1a}}
.item-desc{{font-size:12.5px;color:#333;margin-top:4px;line-height:1.6}}
.proj-link{{font-size:12px;margin-top:5px;color:#555}}
.proj-link a{{color:#1a1a1a;text-decoration:none;border-bottom:1px solid #ccc}}
.gpa-line{{font-size:12px;color:#666;margin-top:3px}}
.skills-wrap{{display:flex;flex-wrap:wrap;gap:6px;margin-top:4px}}
.cert-row{{font-size:13px;color:#333;padding:3px 0;display:flex;align-items:center;gap:6px}}
.summary-text{{font-size:13px;color:#333;line-height:1.75;margin-top:6px}}
.edu-item {{
    margin-bottom: 22px;
    padding-bottom: 12px;
    border-bottom: 1px solid #eee;
}}
.edu-item:last-child {{
    border-bottom: none;
    margin-bottom: 0;
    padding-bottom: 0;
}}

.edu-top-row {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 4px;
}}

.edu-degree {{
    font-size: 15px;
    font-weight: 600;
    color: #1e1b2e;
}}

.edu-year {{
    font-size: 13px;
    font-weight: 500;
    color: #666;
    white-space: nowrap;
}}

.edu-bottom-row {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
}}

.edu-institution {{
    font-size: 13.5px;
    color: #555;
}}

.edu-gpa {{
    font-size: 13px;
    font-weight: 600;
    color: #111;
}}
a{{color:#1a1a1a;text-decoration:none}}
</style></head><body>
<div class="page">
  <div class="hdr">
    <div class="hdr-name">{data.get("name","")}</div>
    <div class="hdr-role">{data.get("target_role","")}</div>
    <div class="hdr-contact">{contact}</div>
  </div>
  {f'<div class="sec"><div class="sec-title">Profile</div><p class="summary-text">{data.get("summary","")}</p></div>' if data.get("summary") else ""}
  {f'<div class="sec"><div class="sec-title">Experience</div>{exp_html}</div>' if exp_html else ""}
  {f'<div class="sec"><div class="sec-title">Projects</div>{proj_html}</div>' if proj_html else ""}
  {f'<div class="sec"><div class="sec-title">Education</div>{edu_html}</div>' if edu_html else ""}
  {f'<div class="sec"><div class="sec-title">Skills</div><div class="skills-wrap">{skills_html}</div></div>' if skills_html else ""}
  {f'<div class="sec"><div class="sec-title">Certifications</div>{cert_html}</div>' if cert_html else ""}
</div></body></html>'''

# ─── TEMPLATE 12: Professional ────────────────────────────
def template_professional(data: dict) -> str:
    contact = ' • '.join(_build_contact_parts(data))
    skills = data.get('skills', [])
    skills_html = ''
    if skills:
        skill_items = ''.join(f'<div class="skill-item">• {s}</div>' for s in skills)
        skills_html = f'<div class="section"><div class="skills-list">{skill_items}</div></div>'

    exp_html = ''
    for job in data.get('experience', []):
        bullets = ''.join(f'<li>{b}</li>' for b in job.get('bullets', []) if b.strip())
        dur = job.get("start_date", "") or job.get("duration", "")
        end = f' — {job.get("end_date","Present")}' if job.get("start_date") else ""
        exp_html += f'''
        <div class="exp-item">
            <div class="exp-header">
                <div class="exp-title">
                    <strong>{job.get("title","")}</strong>
                    <span class="company">at {job.get("company","")}</span>
                </div>
                <span class="date">{dur}{end}</span>
            </div>
            {f'<div class="exp-location">{job.get("location","")}</div>' if job.get("location") else ""}
            <ul class="exp-bullets">{bullets}</ul>
        </div>'''

    proj_html = ''
    for p in data.get('projects', []):
        link_html = f'<div class="proj-link"><strong>Link:</strong> <a href="{p.get("link")}" target="_blank">{p.get("link","")}</a></div>' if p.get("link") else ""
        proj_html += f'''
        <div class="proj-item">
            <div class="proj-name"><strong>{p.get("name","")}</strong></div>
            <div class="proj-tech"><strong>Technologies:</strong> {p.get("tech_stack","")}</div>
            <p class="proj-desc">{p.get("description","")}</p>
            {link_html}
        </div>'''

    # ==================== IMPROVED EDUCATION ====================
    edu_html = ''
    for e in data.get('education', []):
        degree = e.get("degree", "").strip()
        institution = e.get("institution", "").strip()
        year = e.get("graduation_year", "").strip()
        gpa = e.get("gpa", "") or e.get("percentage", "")

        edu_html += f'''
        <div class="edu-item">
            <div class="edu-top-row">
                <span class="edu-degree">{degree}</span>
                <span class="edu-year">{year}</span>
            </div>
            <div class="edu-bottom-row">
                <span class="edu-institution">{institution}</span>
                {f'<span class="edu-gpa">{gpa}</span>' if gpa else ''}
            </div>
        </div>'''

    cert_html = ''.join(f'<div class="cert-item">• {(c.get("name","") if isinstance(c, dict) else str(c))}</div>'
                        for c in data.get('certifications', []) if (c.get("name","") if isinstance(c, dict) else str(c)).strip())

    return f'''<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>{data.get("name","Resume")}</title>
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Playfair+Display:wght@700&display=swap');
    * {{ margin:0; padding:0; box-sizing:border-box; }}
    body {{ font-family: 'Inter', system-ui, sans-serif; background: #fff; color: #1f2937; line-height: 1.65; font-size: 14.2px; }}
    .page {{ max-width: 850px; margin: 30px auto; overflow: visible; background: #ffffff; padding: 45px 55px; box-shadow: 0 10px 40px rgba(0,0,0,0.08); border-radius: 8px; }}
    h1 {{ font-family: 'Playfair Display', serif; font-size: 36px; font-weight: 700; letter-spacing: -1px; margin-bottom: 4px; }}
    .role {{ color: #1e40af; font-size: 18px; font-weight: 500; margin-bottom: 18px; }}
    .contact {{ color: #374151; font-size: 13.5px; margin-bottom: 32px; display: flex; flex-wrap: wrap; gap: 12px; }}
    .sec-title {{ color: #1e40af; font-size: 15.5px; font-weight: 700; letter-spacing: 0.5px; border-bottom: 3px solid #1e40af; padding-bottom: 8px; margin: 32px 0 16px; }}
    
    .exp-item, .proj-item, .edu-item {{ margin-bottom: 26px; }}
    .exp-header {{ display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 6px; flex-wrap: wrap; gap: 8px; }}
    .exp-title strong {{ font-size: 15.5px; }}
    .company {{ color: #374151; font-weight: 600; }}
    .date {{ color: #64748b; font-size: 13.2px; white-space: nowrap; font-weight: 500; }}
    .exp-location {{ color: #64748b; font-size: 13.5px; margin-bottom: 8px; }}
    .exp-bullets li {{ margin-bottom: 7px; padding-left: 4px; }}
    .proj-name {{ font-size: 15.5px; font-weight: 700; margin-bottom: 6px; }}
    .proj-tech {{ color: #1e40af; font-size: 13.2px; margin-bottom: 8px; }}
    .proj-desc {{ color: #374151; margin-bottom: 8px; line-height: 1.6; }}
    .proj-link a {{ color: #2563eb; text-decoration: none; font-size: 13px; }}

    /* ==================== EDUCATION STYLING ==================== */
    .edu-item {{
        margin-bottom: 24px;
        padding-bottom: 14px;
        border-bottom: 1px solid #e5e7eb;
    }}
    .edu-item:last-child {{
        border-bottom: none;
        margin-bottom: 0;
        padding-bottom: 0;
    }}
    .edu-top-row {{
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        margin-bottom: 5px;
    }}
    .edu-degree {{
        font-size: 15.5px;
        font-weight: 600;
        color: #1e2937;
    }}
    .edu-year {{
        font-size: 13.2px;
        font-weight: 500;
        color: #64748b;
        white-space: nowrap;
    }}
    .edu-bottom-row {{
        display: flex;
        justify-content: space-between;
        align-items: baseline;
    }}
    .edu-institution {{
        font-size: 13.5px;
        color: #475569;
    }}
    .edu-gpa {{
        font-size: 13.2px;
        font-weight: 600;
        color: #1e40af;
    }}

    .skill {{ background: #eff6ff; color: #1e40af; padding: 6px 14px; border-radius: 9999px; font-size: 13px; margin: 4px 6px 4px 0; display: inline-block; }}
    @media print {{ body {{ background: white; }} .page {{ box-shadow: none; margin: 0; padding: 35px 45px; max-width: 100%; }} }}
</style></head><body>
    <div class="page">
        <h1>{data.get("name","")}</h1>
        <div class="role">{data.get("target_role","")}</div>
        <div class="contact">{contact}</div>
        {f'<div class="sec-title">PROFESSIONAL SUMMARY</div><p style="color:#374151;line-height:1.75;margin-bottom:28px;">{data.get("summary","")}</p>' if data.get("summary") else ""}
        {f'<div class="sec-title">EXPERIENCE</div>{exp_html}' if exp_html else ""}
        {f'<div class="sec-title">PROJECTS</div>{proj_html}' if proj_html else ""}
        {f'<div class="sec-title">EDUCATION</div>{edu_html}' if edu_html else ""}
        {f'<div class="sec-title">SKILLS</div><div style="margin-top:8px">{skills_html}</div>' if skills_html else ""}
        {f'<div class="sec-title">CERTIFICATIONS</div><p style="color:#374151;margin-top:8px;">{cert_html}</p>' if cert_html else ""}
    </div></body></html>'''
# ─── TEMPLATE 13: Executive Brown ────────────────────────────
def template_executive_brown(data: dict) -> str:
    contact_parts = _build_contact_parts(data)
    contact_html = '  •  '.join(contact_parts)
    skills = data.get('skills', [])
    skills_html = ''
    if skills:
        skill_items = ''.join(f'<div class="skill-item">• {s}</div>' for s in skills)
        skills_html = f'<div class="section"><div class="sec-title">Skills</div><div class="skills-list">{skill_items}</div></div>'
    exp_html = ''
    for job in data.get('experience', []):
        bullets = ''.join(f'<li>{b}</li>' for b in job.get('bullets', []) if b.strip())
        dur = job.get("start_date", "") or job.get("duration", "")
        end = f' – {job.get("end_date", "Present")}' if job.get("start_date") else ""
        date_str = f"{dur}{end}".strip()
        loc = f'<span class="meta-sep">|</span><span class="job-loc">{job.get("location","")}</span>' if job.get("location") else ""
        exp_html += f'''
        <div class="entry">
            <div class="entry-head">
                <div class="entry-left">
                    <span class="entry-title">{job.get("title","")}</span>
                    <span class="meta-sep">·</span>
                    <span class="entry-org">{job.get("company","")}</span>
                    {loc}
                </div>
                <span class="entry-date">{date_str}</span>
            </div>
            <ul>{bullets}</ul>
        </div>'''
    proj_html = ''
    for p in data.get('projects', []):
        link_html = f'<div class="proj-link"><strong>Link:</strong> <a href="{p.get("link")}" target="_blank">{p.get("link","")}</a></div>' if p.get("link") else ""
        proj_html += f'''
        <div class="entry">
            <div class="entry-head"><span class="entry-title">{p.get("name","")}</span></div>
            <div class="proj-tech" style="font-size:13px;color:#4a3320;"><strong>Technologies:</strong> {p.get("tech_stack","")}</div>
            <p class="proj-desc">{p.get("description","")}</p>
            {link_html}
        </div>'''
    edu_html = _build_education_html(data.get('education', []))
    cert_html = ''
    certs = data.get('certifications', [])
    if certs:
        cert_items = ''.join(f'<div class="cert-item">&#10003; {(c.get("name","") if isinstance(c, dict) else str(c))}</div>' for c in certs)
        cert_html = f'<div class="section"><div class="sec-title">Certifications</div>{cert_items}</div>'
    summary_block = f'<div class="section"><div class="sec-title">Professional Summary</div><p class="summary-text">{data.get("summary","")}</p></div>' if data.get("summary") else ""
    exp_block = f'<div class="section"><div class="sec-title">Professional Experience</div>{exp_html}</div>' if exp_html else ""
    proj_block = f'<div class="section"><div class="sec-title">Projects</div>{proj_html}</div>' if proj_html else ""
    edu_block = f'<div class="section"><div class="sec-title">Education</div>{edu_html}</div>' if edu_html else ""
    return f'''<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>{data.get("name", "Resume")}</title>
<style>
    *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0;}}
    body{{font-family:Georgia,'Times New Roman',serif;background:#f5ede0;padding:36px 20px;color:#3a2a1a;}}
    a{{color:#7a4e2d;text-decoration:none;}}
    .resume{{max-width:860px;margin:0 auto;background:#fdf8f2;border:1px solid #d4b896;}}
    .header{{background:#5c3317;color:#fdf8f2;padding:36px 44px 28px;border-bottom:4px solid #a0622a;}}
    .header-name{{font-size:34px;font-weight:normal;letter-spacing:2px;text-transform:uppercase;color:#fdf8f2;}}
    .header-role{{font-size:14px;letter-spacing:3px;text-transform:uppercase;color:#d4ae86;margin-top:6px;font-family:system-ui,sans-serif;}}
    .header-contact{{margin-top:18px;font-size:12.5px;color:#c9a97a;font-family:system-ui,sans-serif;}}
    .body{{display:flex;align-items:stretch;}}
    .left-col{{width:230px;flex-shrink:0;background:#ede0cf;padding:30px 22px;border-right:1px solid #d4b896;}}
    .right-col{{flex:1;padding:30px 36px;}}
    .sec-title{{font-size:10px;font-weight:bold;letter-spacing:2.5px;text-transform:uppercase;color:#7a4e2d;font-family:system-ui,sans-serif;border-bottom:1.5px solid #c4a07a;padding-bottom:5px;margin-bottom:12px;}}
    .section{{margin-bottom:26px;}}
    .skill-item{{font-size:12.5px;color:#4a3320;padding:3px 0;line-height:1.5;}}
    .summary-text{{font-size:13.5px;line-height:1.75;color:#4a3320;}}
    .entry{{margin-bottom:18px;}}
    .edu-item {{
    margin-bottom: 22px;
    padding-bottom: 12px;
    border-bottom: 1px solid #eee;
}}
    .entry-head{{display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:4px;margin-bottom:5px;}}
    .entry-left{{display:flex;flex-wrap:wrap;align-items:baseline;gap:5px;}}
    .entry-title{{font-size:15px;font-weight:bold;color:#3a2010;}}
    .entry-org{{font-size:13.5px;color:#7a4e2d;font-style:italic;}}
    .edu-gpa {{ color: #1e40af; font-size: 13px; }}
    .entry-date{{font-size:12px;color:#9a7a5a;white-space:nowrap;font-family:system-ui,sans-serif;}}
    .meta-sep{{color:#b09070;font-size:12px;}}
    ul{{margin:4px 0 0 16px;padding:0;}}
    li{{font-size:13px;line-height:1.6;color:#4a3320;margin-bottom:3px;}}
    .proj-desc{{font-size:13px;line-height:1.65;color:#4a3320;margin-top:6px;}}
    .edu-item:last-child {{
    border-bottom: none;
    margin-bottom: 0;
    padding-bottom: 0;
}}

.edu-top-row {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 4px;
}}

.edu-degree {{
    font-size: 15px;
    font-weight: 600;
    color: #1e1b2e;
}}

.edu-year {{
    font-size: 13px;
    font-weight: 500;
    color: #7a4e2d;
    white-space: nowrap;
}}

.edu-bottom-row {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
}}

.edu-institution {{
    font-size: 12px;
    color: #7a4e2d;
}}

.edu-gpa {{
    font-size: 12px;
    font-weight: 400;
    color: #000000;
    font-family:system-ui,sans-serif;
}}
    .proj-link{{font-size:12px;margin-top:5px;color:#7a4e2d;font-family:system-ui,sans-serif;}}
    .cert-item{{font-size:12.5px;line-height:1.7;color:#4a3320;font-family:system-ui,sans-serif;}}
    .header-rule{{border:none;border-top:1px solid #a0622a;margin:14px 0 0;opacity:0.5;}}
</style></head><body>
<div class="resume">
    <div class="header">
        <div class="header-name">{data.get("name","")}</div>
        <div class="header-role">{data.get("target_role","")}</div>
        <hr class="header-rule">
        <div class="header-contact">{contact_html}</div>
    </div>
    <div class="body">
        <div class="left-col">{skills_html}{cert_html}</div>
        <div class="right-col">{summary_block}{exp_block}{proj_block}{edu_block}</div>
    </div>
</div></body></html>'''

# ─── TEMPLATE 14: Creative Decor ────────────────────────────
def template_creative_decor(data: dict) -> str:
    contact = ' | '.join(_build_contact_parts(data))
    skills = data.get('skills', [])
    skills_html = ''
    if skills:
        skill_items = ''.join(f'<div class="skill-item">• {s}</div>' for s in skills)
        skills_html = f'<div class="section"><div class="skills-list">{skill_items}</div></div>'
    exp_html = ''
    for job in data.get('experience', []):
        bullets = ''.join(f'<li>{b}</li>' for b in job.get('bullets', []) if b.strip())
        dur = job.get("start_date", "") or job.get("duration", "")
        end = f' — {job.get("end_date","Present")}' if job.get("start_date") else ""
        exp_html += f'''
        <div class="item">
            <strong>{job.get("title","")}</strong>
            <span class="company">at </span><span class="company">{job.get("company","")}</span>
            <span class="date">{dur}{end}</span>
            <div class="item-sub">{(job.get("location","")) if job.get("location") else ""}</div>
            <ul>{bullets}</ul>
        </div>'''
    proj_html = ''
    for p in data.get('projects', []):
        link_html = f'<div style="margin-top:7px;font-size:14px"><strong>Link :</strong> <a href="{p.get("link")}" target="_blank">{p.get("link","")}</a></div>' if p.get("link") else ""
        proj_html += f'''
        <div class="item">
            <div style="margin-bottom:6px"><strong style="font-size:16px">{p.get("name","")}</strong></div>
            <div class="i-sub tech" style="margin-bottom:8px;"><strong style="font-size:14px">Technologies:</strong> {p.get("tech_stack","")}</div>
            <p style="margin:6px 0 10px;line-height:1.6">{p.get("description","")}</p>
            {link_html}
        </div>'''
    edu_html = _build_education_html(data.get('education', []))
    cert_html = ''
    for c in data.get('certifications', []):
        name = c.get('name','') if isinstance(c, dict) else str(c)
        if name.strip(): cert_html += f'<div class="cert-row">🏅 {name}</div>'
    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<title>{data.get("name","Resume")}</title>
<style>
    body{{font-family:'Georgia',serif;background:#fdfaf0;padding:40px;}}
    .resume{{max-width:850px;margin:auto;background:white;padding:50px;box-shadow:0 10px 40px rgba(0,0,0,0.1);position:relative;}}
    .resume::before{{content:"";position:absolute;top:0;left:0;right:0;height:10px;background:linear-gradient(#f4a261,#e76f51);}}
    h1{{font-size:42px;color:#2a2a2a;margin:0 0 8px;}}
    .role{{color:#e76f51;font-size:18px;margin-bottom:20px;}}
    .contact{{color:#555;margin-bottom:30px;}}
    .sec-title{{color:#e76f51;font-size:15px;border-bottom:2px solid #f4a261;padding-bottom:8px;margin:30px 0 15px;}}
    .item{{margin-bottom:22px;}}
    .date{{float:right;color:#777;font-size:13.5px;}}
    .edu-item {{
    margin-bottom: 22px;
    padding-bottom: 12px;
    border-bottom: 1px solid #eee;
}}
.edu-item:last-child {{
    border-bottom: none;
    margin-bottom: 0;
    padding-bottom: 0;
}}

.edu-top-row {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 4px;
}}

.edu-degree {{
    font-size: 15px;
    font-weight: 600;
    color: #1e1b2e;
}}

.edu-year {{
    font-size: 13px;
    font-weight: 500;
    color: #666;
    white-space: nowrap;
}}

.edu-bottom-row {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
}}

.edu-institution {{
    font-size: 13.5px;
    color: #555;
}}

.edu-gpa {{
    font-size: 13px;
    font-family:system-ui;
    font-weight: 600;
    color: #111;
}}
    ul{{padding-left:22px;}}
</style></head><body>
<div class="resume">
    <h1>{data.get("name","")}</h1>
    <div class="role">{data.get("target_role","")}</div>
    <div class="contact">{contact}</div>
    {f'<div class="sec-title">Profile</div><p>{data.get("summary","")}</p>' if data.get("summary") else ""}
    {f'<div class="sec-title">Experience</div>{exp_html}' if exp_html else ""}
    {f'<div class="sec-title">Projects</div>{proj_html}' if proj_html else ""}
    {f'<div class="sec-title">Education</div>{edu_html}' if edu_html else ""}
    {f'<div class="sec-title">Skills</div><p>{skills_html}</p>' if skills_html else ""}
    {f'<div class="sec-title">Certifications</div><p>{cert_html}</p>' if cert_html else ""}
</div></body></html>'''

# ─── TEMPLATE 15: Modern Sidebar ────────────────────────────
def template_modern_sidebar(data: dict) -> str:
    contact = ' • '.join(_build_contact_parts(data))
    skills = data.get('skills', [])
    skills_html = ''
    if skills:
        skill_items = ''.join(f'<div class="skill-item">• {s}</div>' for s in skills)
        skills_html = f'<div class="section"><div class="skills-list">{skill_items}</div></div>'
    exp_html = ''
    for job in data.get('experience', []):
        bullets = ''.join(f'<li>{b}</li>' for b in job.get('bullets', []) if b.strip())
        dur = job.get("start_date", "") or job.get("duration", "")
        end = f' — {job.get("end_date","Present")}' if job.get("start_date") else ""
        date_str = f"{dur}{end}".strip()
        exp_html += f'''
        <div class="exp-item">
            <div class="exp-header">
                <div class="exp-left">
                    <strong>{job.get("title","")}</strong>
                    <span class="at">at</span>
                    <span class="company">{job.get("company","")}</span>
                    {f'<span class="location">· {job.get("location","")}</span>' if job.get("location") else ""}
                </div>
                <div class="date">{date_str}</div>
            </div>
            <ul>{bullets}</ul>
        </div>'''
    proj_html = ''
    for p in data.get('projects', []):
        link_html = f'<div style="margin-top:6px"><strong>Link:</strong> <a href="{p.get("link")}" target="_blank">{p.get("link","")}</a></div>' if p.get("link") else ""
        proj_html += f'''
        <div class="proj">
            <strong>{p.get("name","")}</strong>
            <div class="tech"><strong>Technologies:</strong> {p.get("tech_stack","")}</div>
            <p>{p.get("description","")}</p>
            {link_html}
        </div>'''
    edu_html = _build_education_html(data.get('education', []))
    cert_html = ''.join(f'<div class="cert">✓ {c.get("name","") if isinstance(c, dict) else str(c)}</div>'
                        for c in data.get('certifications', []))
    return f'''<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>{data.get("name","Resume")}</title>
<style>
    body{{font-family:system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f8f9fa;padding:40px 20px;margin:0;}}
    .resume{{max-width:950px;margin:auto;background:white;box-shadow:0 15px 35px rgba(0,0,0,0.08);display:flex;overflow:hidden;}}
    .sidebar{{width:280px;background:#0f172a;color:#e2e8f0;padding:40px 30px;}}
    .main{{flex:1;padding:40px 45px;}}
    .name{{font-size:32px;font-weight:700;margin:0 0 6px;color:white;}}
    .role{{color:#60a5fa;font-size:15.5px;margin-bottom:25px;}}
    .contact-info{{margin:28px 0 35px;font-size:13.8px;line-height:1.8;color:#cbd5e1;}}
    .contact-info a{{color:#93c5fd;text-decoration:none;}}
    .sec-title{{color:#3b82f6;font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:1.2px;margin:28px 0 12px;border-bottom:1px solid #334155;padding-bottom:6px;}}
    .exp-item{{margin-bottom:26px;}}
    .exp-header{{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px;}}
    .exp-left{{flex:1;display:flex;flex-wrap:wrap;align-items:baseline;gap:6px;}}
    .exp-left strong{{font-size:15.5px;color:#1e2937;}}
    .at{{color:#64748b;font-weight:400;}}
    .company{{color:#000000;font-weight:600;}}
    .location{{color:#64748b;font-size:13.5px;}}
    .date{{color:#64748b;font-size:13.5px;font-weight:500;white-space:nowrap;margin-left:20px;flex-shrink:0;}}
    ul{{margin:8px 0 0 20px;padding:0;}}
    li{{margin-bottom:6px;line-height:1.45;}}
    .proj,.edu{{margin-bottom:24px;}}
    .edu-item {{
    margin-bottom: 22px;
    padding-bottom: 12px;
    border-bottom: 1px solid #eee;
}}
.edu-item:last-child {{
    border-bottom: none;
    margin-bottom: 0;
    padding-bottom: 0;
}}

.edu-top-row {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 4px;
}}

.edu-degree {{
    font-size: 15px;
    font-weight: 600;
    color: #1e1b2e;
}}

.edu-year {{
    font-size: 13px;
    font-weight: 500;
    color: #666;
    white-space: nowrap;
}}

.edu-bottom-row {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
}}

.edu-institution {{
    font-size: 13.5px;
    color: #555;
}}

.edu-gpa {{
    font-size: 13px;
    font-weight: 600;
    color: #111;
    font-family:system-ui;
}}
    .tech{{color:#475569;font-size:14px;margin:6px 0;}}
    a{{color:#3b82f6;text-decoration:none;}}
    .cert{{margin-bottom:6px;color:#cbd5e1;font-size:13px;}}
</style></head><body>
<div class="resume">
    <div class="sidebar">
        <div class="name">{data.get("name","")}</div>
        <div class="role">{data.get("target_role","")}</div>
        <div class="contact-info">{contact.replace(" • ", "<br>")}</div>
        {f'<div class="sec-title">Skills</div>{skills_html}' if skills_html else ""}
        {f'<div class="sec-title">Certifications</div>{cert_html}' if cert_html else ""}
    </div>
    <div class="main">
        {f'<div class="sec-title">Summary</div><p style="margin:0 0 20px;line-height:1.5;">{data.get("summary","")}</p>' if data.get("summary") else ""}
        {f'<div class="sec-title">Experience</div>{exp_html}' if exp_html else ""}
        {f'<div class="sec-title">Projects</div>{proj_html}' if proj_html else ""}
        {f'<div class="sec-title">Education</div>{edu_html}' if edu_html else ""}
    </div>
</div></body></html>'''


TEMPLATE_MAP = {
    'executive': template_executive,
    'minimal':   template_minimal,
    'classic':   template_classic,
    'modern':    template_modern,
    'corporate': template_corporate,
    'creative':  template_creative,
    'academic':  template_academic,
    'rosegold':  template_rosegold,
    'forest':    template_forest,
    'slatepro':  template_slatepro,
    'cyber':     template_cyber,
    'professional': template_professional,
    'executive_brown': template_executive_brown,
    'creative_decor': template_creative_decor,
    'modern_sidebar': template_modern_sidebar
}

def generate_pdf_html(data: dict, template: str = 'executive') -> str:
    """Generate clean HTML optimized for PDF — no JS paginator, pure CSS pagination."""
    fn = TEMPLATE_MAP.get(template, template_executive)
    html = fn(data)
    
    # Inject PDF-specific CSS instead of the screen paginator
    PDF_CSS = """<style id="rf-pdf">
@page {
  size: A4;
  margin: 0;
}
html, body {
  margin: 0 !important;
  padding: 0 !important;
  background: #fff !important;
  -webkit-print-color-adjust: exact !important;
  print-color-adjust: exact !important;
}
/* Force A4 width */
.page, .resume, .cv-wrap, .wrapper, .container,
.page > *, .resume > * {
  width: 794px !important;
  max-width: 794px !important;
  min-width: 0 !important;
  margin: 0 auto !important;
  box-shadow: none !important;
  border-radius: 0 !important;
  box-sizing: border-box !important;
}
/* Allow natural height growth */
body, .page, .resume, .cv-wrap,
.body, .layout, .main, .main-col,
.sidebar, .left-col, .side-col {
  overflow: visible !important;
  height: auto !important;
  min-height: 0 !important;
}
/* Section-aware page breaks */
.sec, .section, .sidebar-sec {
  break-inside: avoid !important;
  page-break-inside: avoid !important;
}
.item, .entry, .exp-item, .proj-item, .edu-item,
.card, .proj-card, .xcard, .edu-row,
.cert-row, .cert-item, .cert-it, .cert,
.blist, .bl, .exp-bullets, ul {
  break-inside: avoid !important;
  page-break-inside: avoid !important;
}
.sec-title, h1, h2, h3, h4 {
  break-after: avoid !important;
  page-break-after: avoid !important;
}
.hdr, .header, .top-bar, .hdr-inner {
  break-inside: avoid !important;
  page-break-inside: avoid !important;
}
/* Colors */
* {
  -webkit-print-color-adjust: exact !important;
  print-color-adjust: exact !important;
  color-adjust: exact !important;
}
</style>"""
    
    if '</head>' in html:
        html = html.replace('</head>', PDF_CSS + '\n</head>', 1)
    else:
        html = html + PDF_CSS
    return html

def generate_html_resume(data: dict, template: str = 'executive') -> str:
    fn = TEMPLATE_MAP.get(template, template_executive)
    html = fn(data)
    return inject_a4_css(html)


# ── Routes ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/enhance-summary", methods=["POST"])
def enhance_summary():
    data = request.json
    try:
        summary = ai_enhance_summary(data)
        return jsonify({"success": True, "summary": summary})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/enhance-bullet", methods=["POST"])
def enhance_bullet():
    data = request.json
    try:
        improved = ai_enhance_bullet(
            data.get("job_title", ""),
            data.get("company", ""),
            data.get("bullet", "")
        )
        return jsonify({"success": True, "bullet": improved})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/suggest-skills", methods=["POST"])
def suggest_skills():
    data = request.json
    try:
        skills = ai_suggest_skills(
            data.get("role", ""),
            data.get("existing_skills", [])
        )
        return jsonify({"success": True, "skills": skills})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/ats-score", methods=["POST"])
def ats_score():
    data = request.json
    try:
        result = ai_ats_score(
            data.get("resume", {}),
            data.get("job_description", "")
        )
        return jsonify({"success": True, "result": result})
    except Exception as e:
        print(f"ATS route error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/download-html/<filename>")
def download_html(filename):
    html_path = os.path.join("generated_resumes", filename)
    
    if not os.path.exists(html_path):
        return jsonify({"error": "HTML file not found"}), 404

    try:
        return send_file(
            html_path,
            as_attachment=True,
            download_name=filename,
            mimetype='text/html'
        )
    except Exception as e:
        print("HTML Download Error:", str(e))
        return jsonify({"error": f"Failed to download HTML: {str(e)}"}), 500
    
@app.route("/api/generate-resume", methods=["POST"])
def generate_resume():
    data = request.json
    template = data.pop('template', 'executive')
    try:
        html_content = generate_html_resume(data, template)
        
        # Generate filename
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        filename = f"resume_{data.get('name', 'user').replace(' ', '_')}_{timestamp}.html"
        filepath = os.path.join("generated_resumes", filename)
        
        os.makedirs("generated_resumes", exist_ok=True)
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html_content)
        
        return jsonify({
            "success": True, 
            "html": html_content, 
            "filename": filename
        })
    except Exception as e:
        print("Generate Resume Error:", str(e))
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/generate-doc", methods=["POST"])
def generate_doc():
    payload = request.json
    doc_type = payload.get("type", "resume")
    data     = payload.get("data", {})
    role     = payload.get("role", data.get("target_role", ""))
    company  = payload.get("company", "")
    model    = payload.get("model", "llama-3.3-70b-versatile")

    student_info = f"""
STUDENT PROFILE:
Name: {data.get('name','')}
Target Role: {role}
Email: {data.get('email','')} | Phone: {data.get('phone','')}
Location: {data.get('location','')}
LinkedIn: {data.get('linkedin','')} | GitHub: {data.get('github','')}
Summary: {data.get('summary','')}

EDUCATION:
{chr(10).join(f"- {e.get('degree','')} at {e.get('institution','')} ({e.get('graduation_year','')}), GPA: {e.get('gpa','')}, Achievements: {e.get('achievements','')}" for e in data.get('education',[]))}

EXPERIENCE:
{chr(10).join(f"- {e.get('title','')} at {e.get('company','')} ({e.get('duration','')}) [{e.get('type','')}]{chr(10)}  Bullets: {'; '.join(e.get('bullets',[]))}" for e in data.get('experience',[]))}

SKILLS: {', '.join(data.get('skills',[]))}
Languages: {data.get('languages','')}
Tools: {data.get('tools','')}
Soft Skills: {data.get('soft_skills','')}

PROJECTS:
{chr(10).join(f"- {p.get('name','')} ({p.get('tech_stack','')}){chr(10)}  {p.get('description','')} | Impact: {p.get('highlights','')} | {p.get('link','')}" for p in data.get('projects',[]))}

Target Company: {company or 'a top company'}
Target Role: {role}
"""

    prompts = {
        "resume": f"""You are an expert resume writer. Create a polished, ATS-optimized professional resume.
Format: Contact Info → Professional Summary (3–4 sentences) → Education → Experience (strong action verbs + quantified results) → Projects (highlight impact) → Skills.
Make every bullet impactful with metrics where possible. Clean plain text output.
{student_info}""",
        "coverLetter": f"""You are an expert career coach. Write a compelling, personalized cover letter for {company or 'the target company'} for the role of {role}.
3–4 paragraphs: opening hook, why this company/role, what they bring, strong closing. Plain text.
{student_info}""",
        "portfolio": f"""You are a portfolio copywriter. Write a compelling "About Me" section for this student's portfolio website.
First person, conversational yet professional. 2–3 paragraphs. Make it memorable.
{student_info}""",
        "linkedin": f"""You are a LinkedIn profile expert. Write a powerful LinkedIn "About" section.
Start with a hook. Cover technical strengths, key achievements, what makes them unique. Under 2600 characters.
{student_info}""",
    }

    prompt = prompts.get(doc_type, prompts["resume"])
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1500, temperature=0.7,
        )
        text = response.choices[0].message.content.strip() # type: ignore
        return jsonify({"success": True, "text": text})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/download/<filename>")
def download_resume(filename):
    filepath = os.path.join("generated_resumes", filename)
    if os.path.exists(filepath):
        return send_file(filepath, as_attachment=True, download_name=filename)
    return jsonify({"error": "File not found"}), 404


@app.route("/api/download-pdf/<filename>")
def download_pdf(filename):
    html_path = os.path.join("generated_resumes", filename.replace('.pdf', '.html'))
    pdf_path  = os.path.join("generated_resumes", filename)

    if not os.path.exists(html_path):
        return jsonify({"error": "HTML file not found"}), 404

    try:
        from playwright.sync_api import sync_playwright
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            
            # Load the HTML file
            page.goto(f'file:///{os.path.abspath(html_path)}', 
                      wait_until='networkidle', 
                      timeout=30000)
            
            # Wait for fonts and CSS to load
            page.wait_for_timeout(1200)
            
            # Generate clean PDF
            page.pdf(
                path=pdf_path,
                format='A4',
                print_background=True,
                margin={'top': '0mm', 'right': '0mm', 'bottom': '0mm', 'left': '0mm'}
            )
            browser.close()

        # Check if PDF was created properly
        if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 10000:
            return send_file(
                pdf_path,
                as_attachment=True,
                download_name=filename,
                mimetype='application/pdf'
            )
        else:
            return jsonify({"error": "PDF generation failed - file too small"}), 500

    except ImportError:
        return jsonify({"error": "Playwright not installed. Run:\npip install playwright\nplaywright install chromium"}), 500
    except Exception as e:
        print("PDF Generation Error:", str(e))
        return jsonify({"error": f"PDF generation failed: {str(e)}"}), 500
       
os.makedirs("generated_resumes", exist_ok=True)

if __name__ == "__main__":
    app.run(debug=True, port=5000)