# ResumeForge – AI Resume Builder

A full-stack AI-powered resume builder using Python Flask + Groq API.

## Features
- 6-step guided form (Personal Info, Education, Experience, Skills, Projects, Generate)
- AI-powered professional summary generation
- AI bullet point enhancer for work experience
- AI skill suggestions based on your target role
- ATS score checker against job descriptions
- Generate: Resume, Cover Letter, Portfolio Bio, LinkedIn Summary
- 4 themes: Midnight / Slate / Forest / Amber
- 3 font styles
- Animated canvas background
- Mandatory field validation with modal feedback
- Typewriter animation on generated text
- HTML resume preview & download

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env and add your Groq API key (free at https://console.groq.com/keys)
python app.py
```

Then open http://localhost:5000