# techMoral Careers

A complete, locally runnable careers prototype with a responsive HTML/CSS frontend, Python Flask backend, SQLite application storage and private PDF resume uploads. No Node.js, Azure account, database server or paid service is needed to test it locally.

## Upgrade an existing local copy (login version)

1. Stop the app with Ctrl+C.
2. Back up your existing `instance` folder.
3. Extract this updated ZIP into a temporary folder. Copy its source files over the matching files in your existing `techmoral-careers` folder. Keep your existing `instance` and `.venv` folders; neither is included in the ZIP.
4. Start again with `.\.venv\Scripts\python.exe app.py`.
5. Open `/register`, create a test account and log in. Open My account to see new applications submitted while logged in.

Startup adds the users table and an optional account ID to the existing database. Old applications and resumes remain available through the operator CSV export. Old records are not automatically linked to a new account by email: email ownership is not verified in this prototype.

## Account creation and login

- Public home and company pages; job search, job details, applications and My account require login.
- Signup: name, email, 12–128 character password, confirmation and privacy consent.
- Email matching is case-insensitive. Unique emails prevent duplicate accounts.
- Salted scrypt password hashes; readable passwords are never stored.
- CSRF-protected login, registration and POST-only logout, with an eight-hour session.
- Basic persistent throttle: at most five login attempts per email in a rolling 15-minute window, including successful logins. This is a simple local control; deploy perimeter rate limiting for public traffic as well.
- My account lists only that user's new application references. Received indicates storage, not recruitment progress.
- No email verification, password reset, MFA or admin/recruiter login is connected. Use test credentials locally; decide on these account lifecycle features before public recruitment.

## 1. Run on your Windows machine

Install Python 3.12 or newer from https://www.python.org/downloads/windows/ (include the Python launcher), extract this ZIP, and open PowerShell inside the `techmoral-careers` folder containing `app.py`.

Run these commands one at a time. Activation is not required:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Open **http://127.0.0.1:5000**. Keep the terminal open; Ctrl+C stops it. Alternatively run `start-local.ps1` if your PowerShell policy permits it. If `py` is unavailable, use `python` for the first command.

## 2. What is included

- Home page, searchable job list and individual descriptions for IDs 669693, 669725 and 669800.
- About, life at techMoral, hiring process, FAQs, contact and draft privacy pages.
- Application form with CSRF protection, server-side validation, required consent and PDF upload (up to 5 MB).
- Confirmation reference, persisted applications, private upload directory and local CSV export.
- Candidate registration, login, logout and private My account submissions list.
- Responsive styles, keyboard focus indicators and form labels; no external fonts or JavaScript required.
- Health endpoint: `/health`.

The sample JDs were rewritten from public role descriptions; they are not copied employer ads. Experience ranges, employment type and company prose are illustrative. Locations, work arrangements, contact details and benefits are not invented. There is no email integration, recruiter login, hiring-stage tracking or public admin dashboard. Candidate signup, login and a private submissions page are included.

## 3. Try the full application flow

1. Create an account, log in, then open Find a job; search `Azure`, `C#` or `669725`.
2. Open a role, then Apply for this role.
3. Use fictional applicant details and a small PDF; submit the form.
4. Save the displayed reference. Restart the app: the record remains in SQLite.
5. Invalid email, missing consent or an invalid/oversized PDF is rejected. Re-select the PDF after a validation error.

Default data: `instance/applications.db`, `instance/resumes/` and `instance/.secret`. Keep this folder private. A file extension and PDF signature are checked, but this does not scan a resume for malware.

Export applications from the app folder, using a local operator account:

```powershell
.\.venv\Scripts\python.exe -m flask --app app:create_app export-applications > applications.csv
```

The export contains personal data. It is deliberately not accessible through the website. Resume filenames match the `resume` column. There is no in-app viewer; use a trusted, protected operator workflow.

Run verification:

```powershell
.\.venv\Scripts\python.exe -m unittest -v
```

## 4. Deploy later to an Azure Windows Server VM

Suggested path: browser → IIS (HTTPS) → Waitress on 127.0.0.1:8080 → Flask → SQLite/private resumes.

### A. Prepare the app

1. Copy the source into `C:\Apps\techmoral-careers`. Do not copy the local `.venv` or test applicant data. Install Python on the VM and repeat the virtual environment and dependency commands above.
2. Create `C:\ProgramData\techMoral`. Set NTFS permissions so only your dedicated app account and administrators can access it. Keep it outside the IIS web root. The app account needs Modify on this data folder and Read/Execute on source and Python; it does not need administrator privileges.
3. In a PowerShell terminal, configure and run the backend:

```powershell
Set-Location C:\Apps\techmoral-careers
$env:TECHMORAL_DATA_DIR = 'C:\ProgramData\techMoral'
$env:COOKIE_SECURE = '1'
.\.venv\Scripts\python.exe run_server.py
```

Open http://127.0.0.1:8080/health locally on the VM to verify the backend. `COOKIE_SECURE=1` is for HTTPS; testing form submission over plain HTTP requires omitting that setting. Keep port 8080 bound to localhost and closed in Azure NSG and Windows Firewall.

The app generates a persistent random session secret in the private data folder. Alternatively inject a long random `SECRET_KEY` through your service configuration. Preserve the same secret across restarts and protect its file permissions.

### B. Set up IIS as the public entry point

1. Install the Web Server (IIS) Windows Server role. Install Microsoft's IIS URL Rewrite and Application Request Routing (ARR) extensions.
2. In IIS Manager, select the server → Application Request Routing Cache → Server Proxy Settings → Enable proxy.
3. Create a **separate** IIS root such as `C:\inetpub\techmoral-proxy`. Copy only `deployment\web.config` into it. Never point IIS at the source code or data directories.
4. Create an IIS website pointing to that proxy root. Add your domain and a valid TLS certificate as an HTTPS binding on port 443. The supplied rewrite forwards all routes and query strings to `http://127.0.0.1:8080`.
5. Point your domain DNS A record to the VM public IP. Allow inbound TCP 443 in both the Azure NSG and Windows Firewall. Restrict RDP to your administrative source IP or use Bastion. An optional port 80 endpoint should redirect to HTTPS.
6. Visit `https://YOUR-DOMAIN/health`, the jobs list and a test application. No proxy-header trust is enabled; this application uses relative redirects and does not require it. If you later add absolute URL generation, configure only headers supplied by your trusted proxy.

### C. Keep the backend running after restart

For an initial VM lab, use Windows Task Scheduler:

- Create Task under a dedicated non-admin app account, run whether the user is logged on or not.
- Trigger: At startup.
- Program: `C:\Apps\techmoral-careers\.venv\Scripts\python.exe`.
- Argument: `run_server.py`.
- Start in: `C:\Apps\techmoral-careers`.
- Set `TECHMORAL_DATA_DIR` and `COOKIE_SECURE` as persistent environment variables available to that account before launching the task. Restart the task after changing environment values.
- Enable restart on failure and remove the default stop-after-duration limit.
- Validate after reboot. For production operations, use your organisation's approved Windows service supervisor with monitored logs and restart handling instead of depending on an interactive terminal.

### D. Before collecting real applicants

Approve real company details, JDs, privacy notice, retention/deletion process and contact information. Add email verification and password recovery, upload malware scanning, login/signup/submission rate limits at the edge, recruiter authentication if a dashboard is added, operational monitoring and protected backups. SQLite is suitable for a small single-VM prototype; use a managed database and appropriate file storage if concurrency or multiple app servers grow. Back up database and resumes consistently while writes are paused; exclude applicant data and secrets from source control and public downloads. The VM deployment has not been executed in your Azure account.

## 5. Edit the content

- Jobs and requirements: `jobs.json` (restart after changing it).
- Colours and layout: `static/style.css`.
- Home page: `templates/home.html`.
- Company pages and draft privacy text: `templates/info.html`.
- Backend and validation: `app.py`.
- VM server: `run_server.py`.

## Sources used for role drafting and deployment

Reviewed 7 October 2026. Role drafts deliberately simplify these descriptions; requirements are suggested examples, not approved techMoral policy.

- Azure role: https://job-boards.greenhouse.io/itd/jobs/4354051009
- Azure administrator scope: https://learn.microsoft.com/en-us/credentials/certifications/resources/study-guides/az-104
- EUC role: https://lplfinancial.wd1.myworkdayjobs.com/en-US/India_Ext/job/End-User-Computing--EUC--Engineer-II_R-050421
- Senior .NET role: https://maersk.wd3.myworkdayjobs.com/en-US/Maersk_Careers/job/Senior-Software-Engineer_R184221
- Flask/Waitress Windows hosting: https://flask.palletsprojects.com/en/stable/deploying/waitress/
- IIS reverse proxy: https://learn.microsoft.com/en-us/iis/extensions/url-rewrite-module/reverse-proxy-with-url-rewrite-v2-and-application-request-routing

Authentication implementation references:
- https://werkzeug.palletsprojects.com/en/stable/utils/#werkzeug.security.generate_password_hash
- https://flask.palletsprojects.com/en/stable/web-security/
