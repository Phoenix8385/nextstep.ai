# skills-dictionary

`skills.json` is a flat, ordered list of canonical skill names. The API's
skill extractor (`app/services/ingestion/skill_extractor.py`) matches job
descriptions and resumes against it case-insensitively and reports the
canonical spelling. Keep entries unique (case-insensitive) and prefer the
vendor's own capitalisation (`PostgreSQL`, `Node.js`, `scikit-learn` → `Scikit-learn`).
