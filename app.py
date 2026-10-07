"""techMoral careers: Flask UI, SQLite applications, private PDF uploads."""
import csv
import io
import json
import os
import re
import secrets
import sqlite3
import uuid
import time
from datetime import timedelta
from contextlib import closing
from pathlib import Path
from flask import Flask, abort, flash, redirect, render_template, request, session, url_for, g
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash

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
                      SESSION_COOKIE_HTTPONLY=True, PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
                      SESSION_REFRESH_EACH_REQUEST=False, SESSION_COOKIE_SAMESITE='Lax',
                      SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE') == '1')
    if test_config: app.config.update(test_config)
    data = Path(app.config['DATA_DIR'])
    (data / 'resumes').mkdir(parents=True, exist_ok=True)
    def connect():
        db = sqlite3.connect(data / 'applications.db', timeout=15)
        db.row_factory = sqlite3.Row
        return db
    with closing(connect()) as db, db:
        db.execute('''CREATE TABLE IF NOT EXISTS applications (
        reference TEXT PRIMARY KEY, job_id TEXT NOT NULL, name TEXT NOT NULL,
        email TEXT NOT NULL, phone TEXT NOT NULL, experience TEXT NOT NULL,
        message TEXT NOT NULL, resume TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
        db.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
        columns = {row['name'] for row in db.execute('PRAGMA table_info(applications)')}
        if 'user_id' not in columns:
            db.execute('ALTER TABLE applications ADD COLUMN user_id INTEGER REFERENCES users(id)')
        db.execute('CREATE TABLE IF NOT EXISTS login_attempts (email TEXT NOT NULL, attempted_at REAL NOT NULL)')
        db.execute('CREATE INDEX IF NOT EXISTS attempts_email_time ON login_attempts(email, attempted_at)')
    CSRFProtect(app)
    dummy_hash = generate_password_hash(secrets.token_hex(24))

    @app.before_request
    def load_and_protect():
        g.user = None
        if session.get('user_id'):
            with closing(connect()) as db:
                g.user = db.execute('SELECT id,name,email FROM users WHERE id=?', (session['user_id'],)).fetchone()
            if g.user is None: session.clear()
        if request.endpoint in {'listings', 'detail', 'apply', 'thanks', 'account'} and g.user is None:
            return redirect(url_for('login', next=request.full_path.rstrip('?')))

    def safe_next(value):
        # Allow only known local GET destinations. Never redirect to external URLs.
        if value == '/account' or value == '/jobs' or value.startswith('/jobs?'):
            return value
        if re.fullmatch(r'/(?:jobs|apply)/[0-9]{6}', value): return value
        return url_for('listings')

    def valid_email(value):
        return len(value) <= 254 and re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value)

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        destination = safe_next(request.args.get('next', ''))
        if g.user: return redirect(destination)
        values = {}
        if request.method == 'POST':
            values = {k: request.form.get(k, '').strip() for k in ['name','email']}
            values['email'] = values['email'].casefold()
            password = request.form.get('password', '')
            errors = []
            if not 2 <= len(values['name']) <= 100: errors.append('Enter a name between 2 and 100 characters.')
            if not valid_email(values['email']): errors.append('Enter a valid email address.')
            if not 12 <= len(password) <= 128: errors.append('Choose a password between 12 and 128 characters.')
            if password != request.form.get('confirm_password', ''): errors.append('Your passwords do not match.')
            if request.form.get('consent') != 'yes': errors.append('Please agree to the privacy notice.')
            if not errors:
                try:
                    with closing(connect()) as db, db:
                        db.execute('INSERT INTO users(name,email,password_hash) VALUES(?,?,?)',
                                   (values['name'], values['email'], generate_password_hash(password)))
                except sqlite3.IntegrityError:
                    errors.append('Could not create an account with this email. Try logging in or use another email.')
                else:
                    flash('Account created. Please log in with your email and password.', 'success')
                    return redirect(url_for('login', next=destination))
            for error in errors: flash(error, 'error')
            return render_template('auth.html', title='Create account', mode='register', values=values, destination=destination), 400
        return render_template('auth.html', title='Create account', mode='register', values=values, destination=destination)

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        destination = safe_next(request.args.get('next', ''))
        if g.user: return redirect(destination)
        values = {}
        if request.method == 'POST':
            email = request.form.get('email', '').strip().casefold()[:254]
            password = request.form.get('password', '')
            values['email'] = email
            now = time.time()
            with closing(connect()) as db, db:
                db.execute('DELETE FROM login_attempts WHERE attempted_at < ?', (now - 900,))
                # Reserve an attempt atomically, including concurrent requests.
                count = db.execute('SELECT COUNT(*) FROM login_attempts WHERE email=?', (email,)).fetchone()[0]
                if count >= 5:
                    flash('Too many login attempts. Try again in 15 minutes.', 'error')
                    return render_template('auth.html', title='Log in', mode='login', values=values, destination=destination), 429
                db.execute('INSERT INTO login_attempts VALUES (?,?)', (email, now))
                user = db.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
            matches = check_password_hash(user['password_hash'] if user else dummy_hash, password[:128])
            if user and matches and len(password) <= 128:
                session.clear()
                session['user_id'] = user['id']
                session.permanent = True
                # Keep the attempt window: fresh sessions cannot bypass the throttle.
                return redirect(destination)
            flash('Email or password is incorrect.', 'error')
            return render_template('auth.html', title='Log in', mode='login', values=values, destination=destination), 400
        return render_template('auth.html', title='Log in', mode='login', values=values, destination=destination)

    @app.post('/logout')
    def logout():
        session.clear()
        return redirect(url_for('home'))

    @app.get('/account')
    def account():
        with closing(connect()) as db:
            applications = db.execute('SELECT reference,job_id,created_at FROM applications WHERE user_id=? ORDER BY created_at DESC', (g.user['id'],)).fetchall()
        return render_template('account.html', title='My account', applications=applications)


    @app.context_processor
    def shared(): return {'jobs': JOBS, 'demo': True}

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; form-action 'self'; frame-ancestors 'none'; base-uri 'self'"
        if g.get('user') or request.path.startswith(('/apply', '/thanks', '/login', '/register', '/account', '/jobs')):
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
                with closing(connect()) as db, db:
                    db.execute('INSERT INTO applications (reference,job_id,name,email,phone,experience,message,resume,user_id) VALUES (?,?,?,?,?,?,?,?,?)',
                               (reference, job_id, *[values[k] for k in ['name','email','phone','experience','message']], resume, g.user['id']))
            except Exception:
                path.unlink(missing_ok=True)
                raise
            session['application_reference'] = reference
            return redirect(url_for('thanks'))
        return render_template('apply.html', title='Apply', job=job, values={'name':g.user['name'], 'email':g.user['email']})

    @app.get('/thanks')
    def thanks():
        reference = session.get('application_reference')
        with closing(connect()) as db:
            owned = db.execute('SELECT reference FROM applications WHERE reference=? AND user_id=?', (reference, g.user['id'])).fetchone()
        if not owned: return redirect(url_for('account'))
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
        with closing(connect()) as db, db: rows = db.execute('SELECT * FROM applications ORDER BY created_at DESC').fetchall()
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(['reference','job_id','name','email','phone','experience','message','resume','created_at','user_id'])
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
