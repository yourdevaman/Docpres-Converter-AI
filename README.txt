DOCPRES CONVERTER AI — READY-TO-RUN LOCAL PROJECT

FILES
- app.py: Flask backend and Gemini request handling
- index.html: website UI, styling, upload, results view
- requirements.txt: Python dependencies
- .env.example: safe configuration template (not a real key)
- START-WINDOWS.bat: sets up dependencies and starts the server

QUICK START (WINDOWS)
1. Extract the complete ZIP into a normal folder, e.g. Desktop\Docpres-Converter-AI.
2. Open that extracted folder in VS Code, or double-click START-WINDOWS.bat.
3. On the first run, the launcher creates a .venv and .env, then opens .env in Notepad.
4. In .env, replace the placeholder with a NEW Gemini API key:
   GEMINI_API_KEY=YOUR_NEW_PRIVATE_KEY
   GEMINI_MODEL=gemini-3.8-flash
   Save .env and close Notepad.
5. Double-click START-WINDOWS.bat again. It installs requirements and starts Flask.
6. Keep the terminal window open. Open http://127.0.0.1:5000 in your browser.
7. Check http://127.0.0.1:5000/api/health. It should return JSON with "ok": true.

IMPORTANT
- Use .env, NOT .env.example, for the real key.
- Do not put a real API key in HTML, JavaScript, screenshots, or a public repo.
- Any key already shared in chat should be revoked and replaced.
- The image is sent to Google Gemini to be analyzed; this demo does not save uploads in a local database.
- AI extraction can be wrong. Confirm every medicine name, strength, dose, frequency, and duration with a qualified pharmacist or prescriber.
- This app does not confirm medicine authenticity, clinical safety, or official PMBJP/Janaushadhi equivalence.

DIAGNOSTICS
- If /api/health does not open, inspect the terminal running app.py. Ensure no other old server is using port 5000.
- If /api/health returns "api_configured": false, check that .env is beside app.py and has GEMINI_API_KEY=... on one line, then restart.
- If analysis fails, the frontend shows an API error and the terminal logs the HTTP status. 401 usually means invalid key; 403 can mean key/project permission or eligibility; 404 can mean incorrect model/endpoint; 429 means quota/rate limit.
