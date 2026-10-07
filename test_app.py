import io
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
from app import create_app

class CareersTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)
        self.app = create_app({'TESTING':True,'SECRET_KEY':'test-only','DATA_DIR':self.data})
        self.client = self.app.test_client()
    def tearDown(self): self.tmp.cleanup()
    def form(self):
        html = self.client.get('/apply/669693').get_data(as_text=True)
        token = re.search(r'name="csrf_token" value="([^"]+)"',html).group(1)
        return {'csrf_token':token,'name':'Test Candidate','email':'test@example.invalid',
                'phone':'+91 9000000000','experience':'3–5','message':'Test application',
                'consent':'yes','resume':(io.BytesIO(b'%PDF-1.4\nTest only'),'resume.pdf')}
    def test_pages_filters_and_missing(self):
        for path in ['/','/jobs','/about','/life','/hiring','/faq','/contact','/privacy','/health',
                     '/jobs/669693','/jobs/669725','/jobs/669800','/apply/669800']:
            with self.subTest(path=path): self.assertEqual(self.client.get(path).status_code,200)
        html = self.client.get('/jobs?q=669725').get_data(as_text=True)
        self.assertIn('1 opportunities',html)
        self.assertNotIn('View role <span aria-hidden="true">↗</span></a></article><article',html)
        self.assertIn('0 opportunities',self.client.get('/jobs?q=nomatch').get_data(as_text=True))
        self.assertEqual(self.client.get('/jobs/unknown').status_code,404)
        self.assertEqual(self.client.get('/instance/applications.db').status_code,404)
    def test_submission_persistence_and_export(self):
        response = self.client.post('/apply/669693',data=self.form())
        self.assertEqual(response.status_code,302)
        self.assertIn('saved successfully',self.client.get('/thanks').get_data(as_text=True))
        with sqlite3.connect(self.data/'applications.db') as db:
            row = db.execute('SELECT job_id,email,resume FROM applications').fetchone()
        self.assertEqual(row[:2],('669693','test@example.invalid'))
        self.assertTrue((self.data/'resumes'/row[2]).exists())
        self.assertEqual(self.client.get('/resumes/'+row[2]).status_code,404)
        result = self.app.test_cli_runner().invoke(args=['export-applications'])
        self.assertEqual(result.exit_code,0)
        self.assertIn('test@example.invalid',result.output)
    def test_csrf_and_input_validation(self):
        self.assertEqual(self.client.post('/apply/669693',data={}).status_code,400)
        data = self.form(); data['email']='bad'; data['resume']=(io.BytesIO(b'not pdf'),'bad.pdf')
        response = self.client.post('/apply/669693',data=data)
        self.assertEqual(response.status_code,400)
        self.assertIn('valid email',response.get_data(as_text=True))
        self.assertEqual(list((self.data/'resumes').iterdir()),[])
    def test_file_limit_and_escaping(self):
        data = self.form(); data['resume']=(io.BytesIO(b'%PDF-'+b'x'*(5*1024*1024)),'big.pdf')
        self.assertEqual(self.client.post('/apply/669693',data=data).status_code,400)
        data = self.form(); data['resume']=(io.BytesIO(b'%PDF-'+b'x'*(7*1024*1024)),'huge.pdf')
        self.assertEqual(self.client.post('/apply/669693',data=data).status_code,413)
        html = self.client.get('/jobs?q=%3Cscript%3E').get_data(as_text=True)
        self.assertNotIn('value="<script>"',html)
        self.assertIn('frame-ancestors',self.client.get('/').headers['Content-Security-Policy'])
if __name__ == '__main__': unittest.main()
