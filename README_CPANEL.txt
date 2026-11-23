MyMeta Pro (cPanel Ready-to-Use)
================================
1. Upload & Extract this ZIP directly into your cPanel Python App folder (e.g., mymeta).
2. In cPanel -> Setup Python App:
   - Python version: 3.10 or 3.11
   - Application root: mymeta
   - Application URL: yourdomain.com
   - Application startup file: passenger_wsgi.py
   - Application Entry point: application
3. Add Environment Variable:
   - SECRET_KEY = any-random-strong-password
4. Click "Run Pip Install" -> select requirements.txt
5. Click "Restart" and open https://yourdomain.com
