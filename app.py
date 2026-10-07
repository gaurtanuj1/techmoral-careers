"""techMoral careers: Flask UI, SQLite applications, private PDF uploads."""
import csv
import io
import json
import os
import re
import secrets
import sqlite3
import uuid
from pathlib import Path
from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from flask_wtf.csrf import CSRFProtect

ROOT = Path(__file__).resolve().parent
JOBS = json.loads((ROOT / 'jobs.json').read_text(encoding='utf-8'))

def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    data = Path(os.environ.get('TECHMORAL_DATA_DIR', app.instance_path))
    data.mkdir(parents=True, exist_ok=True)
    secret_file = data / '.secret'
    secret = os.environ.get('SECRET_KEY')
    if not secret:
        if not secret_file.exists():
            secret_file.write_text(secrets.token_hex(32), encoding='utf-8')
            try: secret_file.chmod(0o600)
            except OSError: pass
        secret = secret_file.read_text(encoding='utf-8').strip()
    app.config.update(SECRET_KEY=secret, DATA_DIR=data, MAX_CONTENT_LENGTH=6 * 1024 * 1024,
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                      SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE') == '1')
    if test_config: app.config.update(test_config)
    data = Path(app.config['DATA_DIR'])
    (data / 'resumes').mkdir(parents=True, exist_ok=True)
    def connect():
        db = sqlite3.connect(data / 'applications.db', timeout=15)
        db.row_factory = sqlite3.Row
        return db
    with connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS applications (
        reference TEXT PRIMARY KEY, job_id TEXT NOT NULL, name TEXT NOT NULL,
        email TEXT NOT NULL, phone TEXT NOT NULL, experience TEXT NOT NULL,
        message TEXT NOT NULL, resume TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    CSRFProtect(app)

    @app.context_processor
    def shared(): return {'jobs': JOBS, 'demo': True}

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; form-action 'self'; frame-ancestors 'none'; base-uri 'self'"
        if request.path.startswith(('/apply', '/thanks')):
            response.headers['Cache-Control'] = 'no-store'
        return response

    def get_job(job_id):
        return next((j for j in JOBS if j['id'] == job_id), None) or abort(404)

    @app.get('/')
    def home(): return render_template('home.html', title='Build your next chapter')

    @app.get('/jobs')
    def listings():
        query = request.args.get('q', '').strip()[:100]
        department = request.args.get('department', '')
        matches = [j for j in JOBS if (not query or query.lower() in json.dumps(j).lower())
                   and (not department or j['department'] == department)]
        return render_template('jobs.html', title='Open opportunities', matches=matches, q=query, department=department)

    @app.get('/jobs/<job_id>')
    def detail(job_id): return render_template('detail.html', title=get_job(job_id)['title'], job=get_job(job_id))

    @app.route('/apply/<job_id>', methods=['GET', 'POST'])
    def apply(job_id):
        job = get_job(job_id)
        if request.method == 'POST':
            values = {k: request.form.get(k, '').strip() for k in ['name','email','phone','experience','message']}
            errors = []
            if not 2 <= len(values['name']) <= 100: errors.append('Enter a name between 2 and 100 characters.')
            if len(values['email']) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', values['email']): errors.append('Enter a valid email address.')
            if not re.fullmatch(r'[+\d() .-]{7,25}', values['phone']): errors.append('Enter a valid phone number.')
            if values['experience'] not in ['0–2','3–5','6–8','9+']: errors.append('Select your experience.')
            if len(values['message']) > 2000: errors.append('Your message must be under 2,000 characters.')
            if request.form.get('consent') != 'yes': errors.append('Please agree to the application privacy notice.')
            upload = request.files.get('resume')
            content = upload.read(5 * 1024 * 1024 + 1) if upload else b''
            if not upload or not upload.filename.lower().endswith('.pdf') or not content.startswith(b'%PDF-'):
                errors.append('Upload a PDF résumé.')
            if len(content) > 5 * 1024 * 1024: errors.append('Your résumé must be 5 MB or smaller.')
            if errors:
                for error in errors: flash(error, 'error')
                return render_template('apply.html', title='Apply', job=job, values=values), 400
            reference = uuid.uuid4().hex
            resume = reference + '.pdf'
            path = data / 'resumes' / resume
            path.write_bytes(content)
            try:
                with connect() as db:
                    db.execute('INSERT INTO applications (reference,job_id,name,email,phone,experience,message,resume) VALUES (?,?,?,?,?,?,?,?)',
                               (reference, job_id, *[values[k] for k in ['name','email','phone','experience','message']], resume))
            except Exception:
                path.unlink(missing_ok=True)
                raise
            session['application_reference'] = reference
            return redirect(url_for('thanks'))
        return render_template('apply.html', title='Apply', job=job, values={})

    @app.get('/thanks')
    def thanks():
        reference = session.get('application_reference')
        if not reference: return redirect(url_for('listings'))
        return render_template('thanks.html', title='Application received', reference=reference)

    @app.get('/<page>')
    def information(page):
        if page not in ['about','life','hiring','faq','contact','privacy']: abort(404)
        return render_template('info.html', title={'about':'About techMoral','life':'Life at techMoral','hiring':'How we hire','faq':'Frequently asked questions','contact':'Contact us','privacy':'Application privacy notice'}[page], page=page)

    @app.get('/health')
    def health(): return {'status':'ok'}

    @app.cli.command('export-applications')
    def export():
        """Local operator command; export sensitive applicant data to stdout."""
        import click
        with connect() as db: rows = db.execute('SELECT * FROM applications ORDER BY created_at DESC').fetchall()
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(['reference','job_id','name','email','phone','experience','message','resume','created_at'])
        for row in rows:
            writer.writerow([("'" + str(v)) if str(v).startswith(('=','+','-','@','\t','\r','\n')) else v for v in row])
        click.echo(stream.getvalue(), nl=False)

    @app.errorhandler(404)
    def missing(error): return render_template('error.html', title='Page not found', message='We could not find this page.', code=404), 404
    @app.errorhandler(413)
    def too_large(error): return render_template('error.html', title='File too large', message='Upload a PDF résumé no larger than 5 MB.', code=413), 413
    @app.errorhandler(400)
    def bad_request(error): return render_template('error.html', title='Request could not be processed', message='Refresh the form and try again. Your session may have expired.', code=400), 400
    return app

if __name__ == '__main__':
    create_app().run(host='127.0.0.1', port=5000, debug=False)
