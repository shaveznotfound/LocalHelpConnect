from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, jsonify, send_from_directory)
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import mysql.connector
from mysql.connector import Error
from functools import wraps
from datetime import datetime
import os, json, urllib.request, urllib.parse, time, random, string
import bleach

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY')
redis_url = os.environ.get('REDIS_URL', None)

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode='eventlet',
    message_queue=redis_url   # ← workers now coordinate via Redis
)

UPLOAD_FOLDER = os.path.join(app.root_path, 'static', 'uploads')
ALLOWED_IMAGE = {'jpg', 'jpeg', 'png', 'webp', 'gif'}
ALLOWED_FILE  = {'jpg', 'jpeg', 'png', 'webp', 'gif', 'pdf', 'doc', 'docx', 'txt', 'zip'}
MAX_FILE_BYTES = 10 * 1024 * 1024   # 10 MB

os.makedirs(os.path.join(UPLOAD_FOLDER, 'avatars'), exist_ok=True)
os.makedirs(os.path.join(UPLOAD_FOLDER, 'chat'),    exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

DB_CONFIG = {
    'host': os.environ.get('DB_HOST'),
    'user': os.environ.get('DB_USER'),
    'password': os.environ.get('DB_PASSWORD'),
    'database': os.environ.get('DB_NAME'),
    'port': int(os.environ.get('DB_PORT', 3306)),
    'autocommit': False,
    'charset': 'utf8mb4',
}
def sanitize(text):
    if not text: return ''
    return bleach.clean(str(text), tags=[], attributes={}, strip=True).strip()

def get_db():
    try: return mysql.connector.connect(**DB_CONFIG)
    except Error as e: print(f'[DB ERROR] {e}'); return None

def query_db(sql, params=(), fetchone=False, commit=False):
    conn = get_db()
    if not conn: return None
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, params)
        if commit:
            conn.commit(); return cursor.lastrowid
        return cursor.fetchone() if fetchone else cursor.fetchall()
    except Error as e:
        print(f'[QUERY ERROR] {e}')
        if commit: conn.rollback()
        return None
    finally:
        cursor.close(); conn.close()

def allowed_file(filename, kind='file'):
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    return ext in (ALLOWED_IMAGE if kind == 'image' else ALLOWED_FILE)

def generate_request_id():
    """Generate unique REQ2026XXXX style ID."""
    year = datetime.now().year
    suffix = ''.join(random.choices(string.digits, k=4))
    return f"REQ{year}{suffix}"

def get_unique_request_id():
    for _ in range(20):
        rid = generate_request_id()
        existing = query_db('SELECT id FROM job_requests WHERE request_code=%s', (rid,), fetchone=True)
        if not existing:
            return rid
    return f"REQ{datetime.now().year}{''.join(random.choices(string.digits, k=6))}"

def init_db():
    conn = mysql.connector.connect(
        host=DB_CONFIG['host'], user=DB_CONFIG['user'],
        password=DB_CONFIG['password'], charset='utf8mb4')
    cur = conn.cursor()
    db = DB_CONFIG['database']
    cur.execute(f"CREATE DATABASE IF NOT EXISTS `{db}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    cur.execute(f"USE `{db}`")

    cur.execute("""CREATE TABLE IF NOT EXISTS users (
        id INT AUTO_INCREMENT PRIMARY KEY,
        full_name VARCHAR(100) NOT NULL,
        phone VARCHAR(20) NOT NULL UNIQUE,
        email VARCHAR(120) DEFAULT NULL,
        password_hash VARCHAR(256) NOT NULL,
        role ENUM('customer','worker') NOT NULL,
        is_admin TINYINT(1) NOT NULL DEFAULT 0,
        is_banned TINYINT(1) NOT NULL DEFAULT 0,
        avatar_url VARCHAR(300) DEFAULT NULL,
        login_attempts INT NOT NULL DEFAULT 0,
        locked_until TIMESTAMP NULL,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

    cur.execute("""CREATE TABLE IF NOT EXISTS worker_profiles (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL UNIQUE,
        skills VARCHAR(500) DEFAULT NULL,
        experience VARCHAR(200) DEFAULT NULL,
        description TEXT DEFAULT NULL,
        location VARCHAR(200) DEFAULT NULL,
        lat DECIMAL(10,7) DEFAULT NULL,
        lng DECIMAL(10,7) DEFAULT NULL,
        availability ENUM('available','busy','offline') NOT NULL DEFAULT 'available',
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

    cur.execute("""CREATE TABLE IF NOT EXISTS worker_availability (
        id INT AUTO_INCREMENT PRIMARY KEY,
        worker_id INT NOT NULL,
        blocked_date DATE NOT NULL,
        reason VARCHAR(200) DEFAULT NULL,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uq_worker_date (worker_id, blocked_date),
        FOREIGN KEY (worker_id) REFERENCES users(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

    cur.execute("""CREATE TABLE IF NOT EXISTS job_requests (
        id INT AUTO_INCREMENT PRIMARY KEY,
        request_code VARCHAR(20) NOT NULL UNIQUE,
        customer_id INT NOT NULL,
        worker_id INT NOT NULL,
        description TEXT NOT NULL,
        location VARCHAR(200) NOT NULL,
        category VARCHAR(100) DEFAULT NULL,
        scheduled_at DATETIME DEFAULT NULL,
        status ENUM('pending','accepted','rejected') NOT NULL DEFAULT 'pending',
        job_stage ENUM('accepted','on_the_way','arrived','in_progress','completed') DEFAULT NULL,
        stage_updated_at TIMESTAMP NULL,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        FOREIGN KEY (customer_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (worker_id)   REFERENCES users(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

    cur.execute("""CREATE TABLE IF NOT EXISTS posted_jobs (
        id INT AUTO_INCREMENT PRIMARY KEY,
        customer_id INT NOT NULL,
        title VARCHAR(200) NOT NULL,
        description TEXT NOT NULL,
        location VARCHAR(200) NOT NULL,
        category VARCHAR(100) DEFAULT NULL,
        status ENUM('open','closed') NOT NULL DEFAULT 'open',
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (customer_id) REFERENCES users(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

    cur.execute("""CREATE TABLE IF NOT EXISTS chat_messages (
        id INT AUTO_INCREMENT PRIMARY KEY,
        request_id INT NOT NULL,
        sender_id INT NOT NULL,
        message TEXT DEFAULT NULL,
        msg_type ENUM('text','image','file') NOT NULL DEFAULT 'text',
        file_url VARCHAR(300) DEFAULT NULL,
        file_name VARCHAR(200) DEFAULT NULL,
        file_size INT DEFAULT NULL,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (request_id) REFERENCES job_requests(id) ON DELETE CASCADE,
        FOREIGN KEY (sender_id)  REFERENCES users(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

    cur.execute("""CREATE TABLE IF NOT EXISTS ratings (
        id INT AUTO_INCREMENT PRIMARY KEY,
        request_id INT NOT NULL UNIQUE,
        customer_id INT NOT NULL,
        worker_id INT NOT NULL,
        rating TINYINT NOT NULL,
        rating_punctuality TINYINT DEFAULT NULL,
        rating_quality TINYINT DEFAULT NULL,
        rating_communication TINYINT DEFAULT NULL,
        review TEXT DEFAULT NULL,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (request_id)  REFERENCES job_requests(id) ON DELETE CASCADE,
        FOREIGN KEY (customer_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (worker_id)   REFERENCES users(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

    cur.execute("""CREATE TABLE IF NOT EXISTS reports (
        id INT AUTO_INCREMENT PRIMARY KEY,
        reporter_id INT NOT NULL,
        reported_id INT NOT NULL,
        reason VARCHAR(100) NOT NULL,
        details TEXT DEFAULT NULL,
        status ENUM('pending','reviewed','dismissed') NOT NULL DEFAULT 'pending',
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (reporter_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (reported_id) REFERENCES users(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

    # Backfill request_code for existing rows
    cur.execute("SELECT id FROM job_requests WHERE request_code IS NULL OR request_code=''")
    rows = cur.fetchall()
    for row in rows:
        code = f"REQ{datetime.now().year}{''.join(random.choices(string.digits, k=4))}"
        cur.execute("UPDATE job_requests SET request_code=%s WHERE id=%s", (code, row[0]))

    conn.commit(); cur.close(); conn.close()
    print('[DB] lhc_v7 initialized.')

# ── Constants ──────────────────────────────────────────────────────────────
CATEGORIES = [
    'Electrical','Plumbing','Carpentry','Painting','Cleaning',
    'Appliance Repair','Gardening','HVAC / AC Repair','Roofing',
    'Flooring','Moving & Shifting','Pest Control','Security / CCTV',
    'Welding & Fabrication','IT Support / Tech','Cooking & Catering',
    'Laundry & Ironing','Pet Care','Photography & Video','Tutoring',
    'Interior Design','Driver / Chauffeur','Event Support','Others'
]

STAGE_ORDER  = ['accepted','on_the_way','arrived','in_progress','completed']
STAGE_LABELS = {'accepted':'Request Accepted','on_the_way':'Worker On The Way',
                'arrived':'Worker Arrived','in_progress':'Work In Progress','completed':'Job Completed'}
STAGE_ICONS  = {'accepted':'ph-check-circle','on_the_way':'ph-navigation-arrow',
                'arrived':'ph-map-pin-simple-area','in_progress':'ph-wrench','completed':'ph-seal-check'}
WORKER_NEXT_STAGE = {'accepted':'on_the_way','on_the_way':'arrived','arrived':'in_progress','in_progress':'completed'}
WORKER_NEXT_LABEL = {'accepted':"I'm On My Way",'on_the_way':"I've Arrived",'arrived':'Work Started','in_progress':'Mark as Completed'}

def get_worker_stats(worker_id):
    row = query_db("""SELECT COUNT(DISTINCT jr.id) AS total_completed,
        AVG(r.rating) AS avg_rating, COUNT(DISTINCT r.id) AS total_ratings,
        AVG(r.rating_punctuality) AS avg_punctuality,
        AVG(r.rating_quality) AS avg_quality,
        AVG(r.rating_communication) AS avg_communication
        FROM job_requests jr LEFT JOIN ratings r ON r.request_id=jr.id
        WHERE jr.worker_id=%s AND jr.job_stage='completed'""", (worker_id,), fetchone=True)
    if not row: return {'total_completed':0,'avg_rating':None,'total_ratings':0,
                        'avg_punctuality':None,'avg_quality':None,'avg_communication':None}
    def _r(v): return round(float(v),1) if v else None
    return {'total_completed': row['total_completed'] or 0,
            'avg_rating': _r(row['avg_rating']), 'total_ratings': row['total_ratings'] or 0,
            'avg_punctuality': _r(row['avg_punctuality']),
            'avg_quality': _r(row['avg_quality']),
            'avg_communication': _r(row['avg_communication'])}

def geocode_location(location_text):
    if not location_text: return None, None
    try:
        q = urllib.parse.urlencode({'q':location_text,'format':'json','limit':1})
        req = urllib.request.Request(f'https://nominatim.openstreetmap.org/search?{q}',
                                     headers={'User-Agent':'LocalHelpConnect/1.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        if data: return float(data[0]['lat']), float(data[0]['lon'])
    except Exception as e: print(f'[GEOCODE] {e}')
    return None, None

def get_badge(avg_rating, total_completed):
    if total_completed == 0: return {'label':'New Worker','cls':'badge-new','icon':'ph-star','color':'#6b7280'}
    r = avg_rating or 0
    if r>=4.7 and total_completed>=15: return {'label':'Elite Pro','cls':'badge-elite','icon':'ph-crown','color':'#f59e0b'}
    if r>=4.5 and total_completed>=8:  return {'label':'Trusted Pro','cls':'badge-trusted','icon':'ph-seal-check','color':'#6366f1'}
    if r>=4.0 and total_completed>=4:  return {'label':'Reliable','cls':'badge-reliable','icon':'ph-shield-check','color':'#16a34a'}
    if r>=3.5 and total_completed>=2:  return {'label':'Rising Star','cls':'badge-rising','icon':'ph-trend-up','color':'#0ea5e9'}
    if r<2.5  and total_completed>=3:  return {'label':'Needs Work','cls':'badge-needswork','icon':'ph-warning','color':'#ef4444'}
    return {'label':'Getting Started','cls':'badge-starting','icon':'ph-rocket-launch','color':'#8b5cf6'}

def avatar_url(user):
    """Return avatar URL or None."""
    if user and user.get('avatar_url'):
        return user['avatar_url']
    return None

app.jinja_env.globals.update(
    get_badge=get_badge, avatar_url=avatar_url,
    STAGE_LABELS=STAGE_LABELS, STAGE_ICONS=STAGE_ICONS, STAGE_ORDER=STAGE_ORDER)

# ── Auth decorators ────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def d(*a,**k):
        if 'user_id' not in session: flash('Please login.','warning'); return redirect(url_for('login'))
        return f(*a,**k)
    return d

def role_required(role):
    def dec(f):
        @wraps(f)
        def d(*a,**k):
            if session.get('role')!=role: flash('Access denied.','danger'); return redirect(url_for('dashboard'))
            return f(*a,**k)
        return d
    return dec

def admin_required(f):
    @wraps(f)
    def d(*a,**k):
        if 'user_id' not in session: flash('Please login.','warning'); return redirect(url_for('login'))
        if not session.get('is_admin'): flash('Admin required.','danger'); return redirect(url_for('dashboard'))
        return f(*a,**k)
    return d

# ── Static uploads ─────────────────────────────────────────────────────────
@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

# ── Index ──────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    if 'user_id' in session: return redirect(url_for('dashboard'))
    return render_template('index.html')

# ── Register ───────────────────────────────────────────────────────────────
@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        full_name = sanitize(request.form.get('full_name',''))
        phone     = sanitize(request.form.get('phone',''))
        email     = sanitize(request.form.get('email',''))
        password  = request.form.get('password','')
        confirm   = request.form.get('confirm_password','')
        role      = request.form.get('role','customer')
        errors = []
        if not full_name:         errors.append('Full name required.')
        if not phone:             errors.append('Phone required.')
        if len(password)<6:       errors.append('Password min 6 chars.')
        if password!=confirm:     errors.append('Passwords mismatch.')
        if role not in ('customer','worker'): errors.append('Invalid role.')
        if errors:
            for e in errors: flash(e,'danger')
            return render_template('register.html', form_data=request.form)
        if query_db('SELECT id FROM users WHERE phone=%s',(phone,),fetchone=True):
            flash('Phone already registered.','danger')
            return render_template('register.html', form_data=request.form)
        uid = query_db('INSERT INTO users (full_name,phone,email,password_hash,role) VALUES (%s,%s,%s,%s,%s)',
                       (full_name,phone,email or None,generate_password_hash(password),role),commit=True)
        if uid:
            avatar_file = request.files.get('avatar')
            if avatar_file and avatar_file.filename and allowed_file(avatar_file.filename, 'image'):
                ext = avatar_file.filename.rsplit('.',1)[-1].lower()
                fname = secure_filename(f"avatar_{uid}.{ext}")
                avatar_file.save(os.path.join(UPLOAD_FOLDER, 'avatars', fname))
                av_url = f"/uploads/avatars/{fname}"
                query_db('UPDATE users SET avatar_url=%s WHERE id=%s', (av_url, uid), commit=True)
            if role=='worker': query_db('INSERT INTO worker_profiles (user_id) VALUES (%s)',(uid,),commit=True)
            flash('Account created! Login now.','success'); return redirect(url_for('login'))
        flash('Registration failed.','danger')
    return render_template('register.html', form_data={})

# ── Login ──────────────────────────────────────────────────────────────────
@app.route('/login', methods=['GET','POST'])
def login():
    if 'user_id' in session: return redirect(url_for('dashboard'))
    if request.method == 'POST':
        phone    = sanitize(request.form.get('phone',''))
        password = request.form.get('password','')
        user = query_db('SELECT * FROM users WHERE phone=%s',(phone,),fetchone=True)
        if not user: flash('Invalid credentials.','danger'); return render_template('login.html')
        if user.get('locked_until') and user['locked_until']>datetime.now():
            flash('Account locked. Try later.','danger'); return render_template('login.html')
        if check_password_hash(user['password_hash'],password):
            if user.get('is_banned'): flash('Account banned.','danger'); return render_template('login.html')
            query_db('UPDATE users SET login_attempts=0,locked_until=NULL WHERE id=%s',(user['id'],),commit=True)
            session.clear()
            session.update({'user_id':user['id'],'full_name':user['full_name'],'role':user['role'],
                            'phone':user['phone'],'is_admin':bool(user.get('is_admin',0)),
                            'avatar_url': user.get('avatar_url') or ''})
            flash(f"Welcome, {user['full_name']}!",'success')
            return redirect(url_for('admin_dashboard') if session['is_admin'] else url_for('dashboard'))
        attempts = (user.get('login_attempts') or 0)+1
        if attempts>=5:
            query_db('UPDATE users SET login_attempts=%s,locked_until=DATE_ADD(NOW(),INTERVAL 15 MINUTE) WHERE id=%s',
                     (attempts,user['id']),commit=True)
            flash('Locked 15 min.','danger')
        else:
            query_db('UPDATE users SET login_attempts=%s WHERE id=%s',(attempts,user['id']),commit=True)
            flash(f'Wrong. {5-attempts} left.','danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear(); flash('Logged out.','info'); return redirect(url_for('index'))

# ── Dashboard ──────────────────────────────────────────────────────────────
@app.route('/dashboard')
@login_required
def dashboard():
    uid,role = session['user_id'],session['role']
    if role=='customer':
        reqs = query_db("""SELECT jr.*,u.full_name as worker_name,wp.skills as worker_skills,
            u.avatar_url as worker_avatar
            FROM job_requests jr JOIN users u ON jr.worker_id=u.id
            LEFT JOIN worker_profiles wp ON wp.user_id=u.id
            WHERE jr.customer_id=%s ORDER BY jr.created_at DESC LIMIT 5""",(uid,))
        stats = {
            'pending':    query_db("SELECT COUNT(*) as c FROM job_requests WHERE customer_id=%s AND status='pending'",(uid,),fetchone=True)['c'],
            'accepted':   query_db("SELECT COUNT(*) as c FROM job_requests WHERE customer_id=%s AND status='accepted'",(uid,),fetchone=True)['c'],
            'completed':  query_db("SELECT COUNT(*) as c FROM job_requests WHERE customer_id=%s AND job_stage='completed'",(uid,),fetchone=True)['c'],
            'total':      query_db('SELECT COUNT(*) as c FROM job_requests WHERE customer_id=%s',(uid,),fetchone=True)['c'],
            'posted_jobs':query_db("SELECT COUNT(*) as c FROM posted_jobs WHERE customer_id=%s AND status='open'",(uid,),fetchone=True)['c'],
        }
        user = query_db('SELECT * FROM users WHERE id=%s',(uid,),fetchone=True)
        return render_template('dashboard_customer.html', requests=reqs, stats=stats, user=user)
    # worker
    profile = query_db('SELECT * FROM worker_profiles WHERE user_id=%s',(uid,),fetchone=True)
    incoming = query_db("""SELECT jr.*,u.full_name as customer_name,u.phone as customer_phone,
        u.avatar_url as customer_avatar
        FROM job_requests jr JOIN users u ON jr.customer_id=u.id
        WHERE jr.worker_id=%s ORDER BY jr.created_at DESC LIMIT 5""",(uid,))
    wstats = get_worker_stats(uid)
    stats = {
        'pending':   query_db("SELECT COUNT(*) as c FROM job_requests WHERE worker_id=%s AND status='pending'",(uid,),fetchone=True)['c'],
        'accepted':  query_db("SELECT COUNT(*) as c FROM job_requests WHERE worker_id=%s AND status='accepted'",(uid,),fetchone=True)['c'],
        'completed': wstats['total_completed'],
        'avg_rating': wstats['avg_rating'],
        'total':     query_db('SELECT COUNT(*) as c FROM job_requests WHERE worker_id=%s',(uid,),fetchone=True)['c'],
        'rejected':  query_db("SELECT COUNT(*) as c FROM job_requests WHERE worker_id=%s AND status='rejected'",(uid,),fetchone=True)['c'],
    }
    user = query_db('SELECT * FROM users WHERE id=%s',(uid,),fetchone=True)
    month_jobs = query_db("""SELECT COUNT(*) as c FROM job_requests
        WHERE worker_id=%s AND job_stage='completed'
        AND MONTH(created_at)=MONTH(NOW()) AND YEAR(created_at)=YEAR(NOW())""",(uid,),fetchone=True)
    stats['month_jobs'] = month_jobs['c'] if month_jobs else 0
    return render_template('dashboard_worker.html',profile=profile,requests=incoming,
                           stats=stats,badge=get_badge(wstats['avg_rating'],wstats['total_completed']),
                           wstats=wstats, user=user)

# ── Profile ────────────────────────────────────────────────────────────────
@app.route('/profile', methods=['GET','POST'])
@login_required
@role_required('worker')
def worker_profile():
    uid = session['user_id']
    if request.method=='POST':
        skills=sanitize(request.form.get('skills','')); experience=sanitize(request.form.get('experience',''))
        description=sanitize(request.form.get('description','')); location=sanitize(request.form.get('location',''))
        availability=request.form.get('availability','available')
        try:
            lat = float(request.form.get('lat','')) if request.form.get('lat','').strip() else None
            lng = float(request.form.get('lng','')) if request.form.get('lng','').strip() else None
        except (ValueError, TypeError):
            lat, lng = None, None
        if lat is None or lng is None:
            lat, lng = geocode_location(location)
        query_db("""INSERT INTO worker_profiles (user_id,skills,experience,description,location,availability,lat,lng)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE
            skills=%s,experience=%s,description=%s,location=%s,availability=%s,lat=%s,lng=%s""",
            (uid,skills,experience,description,location,availability,lat,lng,
             skills,experience,description,location,availability,lat,lng),commit=True)
        flash('Profile updated!','success'); return redirect(url_for('worker_profile'))
    profile = query_db('SELECT * FROM worker_profiles WHERE user_id=%s',(uid,),fetchone=True)
    user    = query_db('SELECT * FROM users WHERE id=%s',(uid,),fetchone=True)
    wstats  = get_worker_stats(uid)
    blocked = query_db('SELECT blocked_date,reason FROM worker_availability WHERE worker_id=%s ORDER BY blocked_date',(uid,)) or []
    blocked_dates = [str(r['blocked_date']) for r in blocked]
    return render_template('worker_profile.html',profile=profile,user=user,
                           wstats=wstats,badge=get_badge(wstats['avg_rating'],wstats['total_completed']),
                           blocked_dates=blocked_dates,blocked=blocked)

@app.route('/profile/block-date', methods=['POST'])
@login_required
@role_required('worker')
def block_date():
    uid=session['user_id']; date=request.form.get('date','').strip(); reason=sanitize(request.form.get('reason',''))
    if not date: flash('Select a date.','danger'); return redirect(url_for('worker_profile'))
    query_db("""INSERT INTO worker_availability (worker_id,blocked_date,reason) VALUES (%s,%s,%s)
        ON DUPLICATE KEY UPDATE reason=%s""",(uid,date,reason,reason),commit=True)
    flash(f'Date {date} blocked.','success'); return redirect(url_for('worker_profile'))

@app.route('/profile/unblock-date', methods=['POST'])
@login_required
@role_required('worker')
def unblock_date():
    uid=session['user_id']; date=request.form.get('date','').strip()
    query_db('DELETE FROM worker_availability WHERE worker_id=%s AND blocked_date=%s',(uid,date),commit=True)
    flash(f'{date} unblocked.','success'); return redirect(url_for('worker_profile'))

# ── Avatar upload ──────────────────────────────────────────────────────────
@app.route('/upload-avatar', methods=['POST'])
@login_required
def upload_avatar():
    uid = session['user_id']
    f = request.files.get('avatar')
    if not f or not f.filename:
        flash('No file selected.','danger'); return redirect(request.referrer or url_for('account_settings'))
    if not allowed_file(f.filename, 'image'):
        flash('Only image files allowed.','danger'); return redirect(request.referrer or url_for('account_settings'))
    ext = f.filename.rsplit('.',1)[-1].lower()
    fname = secure_filename(f"avatar_{uid}.{ext}")
    f.save(os.path.join(UPLOAD_FOLDER, 'avatars', fname))
    av_url = f"/uploads/avatars/{fname}"
    query_db('UPDATE users SET avatar_url=%s WHERE id=%s',(av_url,uid),commit=True)
    session['avatar_url'] = av_url
    flash('Profile picture updated!','success')
    return redirect(request.referrer or url_for('account_settings'))

# ── Search ─────────────────────────────────────────────────────────────────
@app.route('/search')
def search_workers():
    skill=sanitize(request.args.get('skill','')); location=sanitize(request.args.get('location',''))
    sql="""SELECT u.id,u.full_name,u.avatar_url,wp.skills,wp.experience,wp.description,wp.location,
               wp.availability,wp.lat,wp.lng,
               COALESCE(AVG(r.rating),NULL) AS avg_rating,
               COUNT(DISTINCT CASE WHEN jr.job_stage='completed' THEN jr.id END) AS total_completed,
               COUNT(DISTINCT r.id) AS total_ratings
        FROM users u JOIN worker_profiles wp ON wp.user_id=u.id
        LEFT JOIN job_requests jr ON jr.worker_id=u.id
        LEFT JOIN ratings r ON r.worker_id=u.id
        WHERE u.role='worker' AND wp.availability!='offline' AND u.is_banned=0"""
    params=[]
    if skill:    sql+=' AND wp.skills LIKE %s'; params.append(f'%{skill}%')
    if location: sql+=' AND wp.location LIKE %s'; params.append(f'%{location}%')
    sql+=' GROUP BY u.id,u.full_name,u.avatar_url,wp.skills,wp.experience,wp.description,wp.location,wp.availability,wp.lat,wp.lng'
    sql+=' ORDER BY avg_rating DESC,total_completed DESC,u.full_name'
    workers=query_db(sql,params) or []
    out=[]
    for w in workers:
        avg_r=round(float(w['avg_rating']),1) if w['avg_rating'] else None
        out.append({**w,'avg_rating':avg_r,'badge':get_badge(avg_r,w['total_completed'])})
    return render_template('search.html',workers=out,skill=skill,location=location)

@app.route('/api/workers/map')
def api_workers_map():
    skill=sanitize(request.args.get('skill','')); location=sanitize(request.args.get('location',''))
    sql="""SELECT u.id,u.full_name,u.avatar_url,wp.skills,wp.location,wp.availability,
               wp.description,wp.experience,wp.lat,wp.lng,
               COALESCE(AVG(r.rating),NULL) AS avg_rating,
               COUNT(DISTINCT CASE WHEN jr.job_stage='completed' THEN jr.id END) AS total_completed,
               COUNT(DISTINCT r.id) AS total_ratings
        FROM users u JOIN worker_profiles wp ON wp.user_id=u.id
        LEFT JOIN job_requests jr ON jr.worker_id=u.id
        LEFT JOIN ratings r ON r.worker_id=u.id
        WHERE u.role='worker' AND wp.availability!='offline'
          AND wp.lat IS NOT NULL AND wp.lng IS NOT NULL AND u.is_banned=0"""
    params=[]
    if skill:    sql+=' AND wp.skills LIKE %s'; params.append(f'%{skill}%')
    if location: sql+=' AND wp.location LIKE %s'; params.append(f'%{location}%')
    sql+=' GROUP BY u.id,u.full_name,u.avatar_url,wp.skills,wp.location,wp.availability,wp.description,wp.experience,wp.lat,wp.lng'
    workers=query_db(sql,params) or []
    result=[]
    for w in workers:
        avg_r=round(float(w['avg_rating']),1) if w['avg_rating'] else None
        badge=get_badge(avg_r,w['total_completed'])
        result.append({'id':w['id'],'name':w['full_name'],'lat':float(w['lat']),'lng':float(w['lng']),
            'location':w['location'] or '','availability':w['availability'],
            'skills':[s.strip() for s in (w['skills'] or '').split(',') if s.strip()][:4],
            'avg_rating':avg_r,'total_completed':w['total_completed'],'total_ratings':w['total_ratings'],
            'description':(w['description'] or '')[:100],'experience':w['experience'] or '',
            'badge_label':badge['label'],'badge_color':badge['color'],
            'avatar_url': w.get('avatar_url') or '',
            'is_customer':session.get('role')=='customer'})
    return jsonify(result)

# ── Hire ───────────────────────────────────────────────────────────────────
@app.route('/hire/<int:worker_id>', methods=['GET','POST'])
@login_required
@role_required('customer')
def hire_worker(worker_id):
    worker=query_db("""SELECT u.id,u.full_name,u.avatar_url,wp.skills,wp.location,wp.description,wp.availability
        FROM users u JOIN worker_profiles wp ON wp.user_id=u.id
        WHERE u.id=%s AND u.role='worker'""",(worker_id,),fetchone=True)
    if not worker: flash('Worker not found.','danger'); return redirect(url_for('search_workers'))
    blocked=query_db('SELECT blocked_date FROM worker_availability WHERE worker_id=%s',(worker_id,)) or []
    blocked_dates=[str(r['blocked_date']) for r in blocked]
    if request.method=='POST':
        description=sanitize(request.form.get('description','')); location=sanitize(request.form.get('location',''))
        category=sanitize(request.form.get('category','')); scheduled_at=request.form.get('scheduled_at','').strip() or None
        if not description or not location: flash('Description and location required.','danger'); return render_template('hire.html',worker=worker,blocked_dates=blocked_dates,CATEGORIES=CATEGORIES)
        try:
            customer_budget = float(request.form.get('customer_budget','')) if request.form.get('customer_budget','').strip() else None
        except ValueError:
            customer_budget = None
        request_code = get_unique_request_id()
        query_db('INSERT INTO job_requests (request_code,customer_id,worker_id,description,location,category,scheduled_at,customer_budget) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                 (request_code,session['user_id'],worker_id,description,location,category,scheduled_at,customer_budget),commit=True)
        flash(f"Request {request_code} sent to {worker['full_name']}!",'success'); return redirect(url_for('my_requests'))
    return render_template('hire.html',worker=worker,blocked_dates=blocked_dates,CATEGORIES=CATEGORIES)

@app.route('/post-job', methods=['GET','POST'])
@login_required
@role_required('customer')
def post_job():
    if request.method=='POST':
        title=sanitize(request.form.get('title','')); description=sanitize(request.form.get('description',''))
        location=sanitize(request.form.get('location','')); category=sanitize(request.form.get('category',''))
        if not title or not description or not location: flash('Title, desc, location required.','danger'); return render_template('post_job.html',CATEGORIES=CATEGORIES)
        query_db('INSERT INTO posted_jobs (customer_id,title,description,location,category) VALUES (%s,%s,%s,%s,%s)',
                 (session['user_id'],title,description,location,category),commit=True)
        flash('Job posted!','success'); return redirect(url_for('dashboard'))
    return render_template('post_job.html',CATEGORIES=CATEGORIES)

@app.route('/my-requests')
@login_required
@role_required('customer')
def my_requests():
    uid=session['user_id']; sf=request.args.get('status','')
    sql="""SELECT jr.*,u.full_name as worker_name,u.phone as worker_phone,u.avatar_url as worker_avatar,
               wp.skills as worker_skills,r.id as rating_id,r.rating as my_rating
        FROM job_requests jr JOIN users u ON jr.worker_id=u.id
        LEFT JOIN worker_profiles wp ON wp.user_id=u.id
        LEFT JOIN ratings r ON r.request_id=jr.id
        WHERE jr.customer_id=%s"""
    params=[uid]
    if sf in ('pending','accepted','rejected'): sql+=' AND jr.status=%s'; params.append(sf)
    sql+=' ORDER BY jr.created_at DESC'
    return render_template('my_requests.html',requests=query_db(sql,params),status_filter=sf)

@app.route('/incoming-requests')
@login_required
@role_required('worker')
def incoming_requests():
    uid=session['user_id']; sf=request.args.get('status','')
    sql="""SELECT jr.*,u.full_name as customer_name,u.phone as customer_phone,u.avatar_url as customer_avatar
        FROM job_requests jr JOIN users u ON jr.customer_id=u.id WHERE jr.worker_id=%s"""
    params=[uid]
    if sf in ('pending','accepted','rejected'): sql+=' AND jr.status=%s'; params.append(sf)
    sql+=' ORDER BY jr.created_at DESC'
    return render_template('incoming_requests.html',requests=query_db(sql,params),status_filter=sf,
                           WORKER_NEXT_STAGE=WORKER_NEXT_STAGE,WORKER_NEXT_LABEL=WORKER_NEXT_LABEL)

@app.route('/request/<int:req_id>/update', methods=['POST'])
@login_required
@role_required('worker')
def update_request(req_id):
    new_status=request.form.get('status','')
    if new_status not in ('accepted','rejected'): flash('Invalid status.','danger'); return redirect(url_for('incoming_requests'))
    req=query_db('SELECT * FROM job_requests WHERE id=%s AND worker_id=%s',(req_id,session['user_id']),fetchone=True)
    if not req: flash('Not found.','danger'); return redirect(url_for('incoming_requests'))
    if new_status=='accepted':
        query_db("UPDATE job_requests SET status=%s,job_stage='accepted',stage_updated_at=NOW() WHERE id=%s",(new_status,req_id),commit=True)
    else:
        query_db('UPDATE job_requests SET status=%s WHERE id=%s',(new_status,req_id),commit=True)
    flash(f'Request {new_status}.','success'); return redirect(url_for('incoming_requests'))

# ── Worker price response ──────────────────────────────────────────────────
@app.route('/request/<int:req_id>/price', methods=['POST'])
@login_required
@role_required('worker')
def worker_price_response(req_id):
    req=query_db('SELECT * FROM job_requests WHERE id=%s AND worker_id=%s',(req_id,session['user_id']),fetchone=True)
    if not req: flash('Not found.','danger'); return redirect(url_for('incoming_requests'))
    action=request.form.get('action','')
    if action=='accept':
        query_db("UPDATE job_requests SET price_status='agreed' WHERE id=%s",(req_id,),commit=True)
        flash('You accepted the customer\'s budget. Price agreed!','success')
    elif action=='counter':
        try:
            counter=float(request.form.get('counter_price',''))
        except ValueError:
            flash('Enter a valid counter price.','danger'); return redirect(url_for('incoming_requests'))
        query_db("UPDATE job_requests SET price_status='countered',worker_counter=%s WHERE id=%s",(counter,req_id),commit=True)
        flash(f'Counter-offer of ₹{counter:.0f} sent to customer.','success')
    return redirect(url_for('incoming_requests'))

# ── Customer price response ────────────────────────────────────────────────
@app.route('/request/<int:req_id>/accept-price', methods=['POST'])
@login_required
@role_required('customer')
def customer_price_response(req_id):
    req=query_db('SELECT * FROM job_requests WHERE id=%s AND customer_id=%s',(req_id,session['user_id']),fetchone=True)
    if not req: flash('Not found.','danger'); return redirect(url_for('my_requests'))
    action=request.form.get('action','')
    if action=='accept':
        query_db("UPDATE job_requests SET price_status='agreed' WHERE id=%s",(req_id,),commit=True)
        flash('You accepted the worker\'s counter-offer. Price agreed!','success')
    elif action=='reject':
        query_db("UPDATE job_requests SET price_status='open',worker_counter=NULL WHERE id=%s",(req_id,),commit=True)
        flash('Counter-offer rejected. Negotiation reset.','info')
    return redirect(url_for('my_requests'))

# ── Stage update — FIX: added missing @app.route decorator ────────────────
@app.route('/request/<int:req_id>/stage', methods=['POST'])
@login_required
@role_required('worker')
def update_stage(req_id):
    req=query_db("SELECT * FROM job_requests WHERE id=%s AND worker_id=%s AND status='accepted'",(req_id,session['user_id']),fetchone=True)
    if not req: flash('Not found.','danger'); return redirect(url_for('incoming_requests'))
    current=req.get('job_stage') or 'accepted'
    next_stage=WORKER_NEXT_STAGE.get(current)
    if not next_stage: flash('Already completed.','info'); return redirect(url_for('incoming_requests'))
    query_db('UPDATE job_requests SET job_stage=%s,stage_updated_at=NOW() WHERE id=%s',(next_stage,req_id),commit=True)
    flash(f"Stage: {STAGE_LABELS[next_stage]}",'success'); return redirect(url_for('incoming_requests'))

@app.route('/track/<int:req_id>')
@login_required
@role_required('customer')
def track_job(req_id):
    uid=session['user_id']
    req=query_db("""SELECT jr.*,u.full_name AS worker_name,u.phone AS worker_phone,u.avatar_url AS worker_avatar,
        wp.skills AS worker_skills,wp.location AS worker_location,
        r.rating AS my_rating,r.id AS rating_id
        FROM job_requests jr JOIN users u ON jr.worker_id=u.id
        LEFT JOIN worker_profiles wp ON wp.user_id=u.id
        LEFT JOIN ratings r ON r.request_id=jr.id
        WHERE jr.id=%s AND jr.customer_id=%s AND jr.status='accepted'""",(req_id,uid),fetchone=True)
    if not req: flash('Only for accepted requests.','danger'); return redirect(url_for('my_requests'))
    wstats=get_worker_stats(req['worker_id'])
    return render_template('track.html',req=req,wstats=wstats,badge=get_badge(wstats['avg_rating'],wstats['total_completed']),
                           STAGE_ORDER=STAGE_ORDER,STAGE_LABELS=STAGE_LABELS,STAGE_ICONS=STAGE_ICONS)

@app.route('/api/track/<int:req_id>')
@login_required
def api_track_status(req_id):
    uid=session['user_id']
    req=query_db('SELECT jr.job_stage,jr.stage_updated_at,jr.status FROM job_requests jr WHERE jr.id=%s AND (jr.customer_id=%s OR jr.worker_id=%s)',
                 (req_id,uid,uid),fetchone=True)
    if not req: return jsonify({'error':'not found'}),404
    stage=req['job_stage'] or 'accepted'
    return jsonify({'stage':stage,'label':STAGE_LABELS.get(stage,stage),
        'updated':req['stage_updated_at'].strftime('%I:%M %p, %d %b') if req['stage_updated_at'] else None,
        'stage_index':STAGE_ORDER.index(stage) if stage in STAGE_ORDER else 0})

@app.route('/rate/<int:req_id>', methods=['GET','POST'])
@login_required
@role_required('customer')
def rate_worker(req_id):
    uid=session['user_id']
    req=query_db("""SELECT jr.*,u.full_name AS worker_name,wp.skills AS worker_skills
        FROM job_requests jr JOIN users u ON jr.worker_id=u.id
        LEFT JOIN worker_profiles wp ON wp.user_id=u.id
        WHERE jr.id=%s AND jr.customer_id=%s AND jr.job_stage='completed'""",(req_id,uid),fetchone=True)
    if not req: flash('Only for completed jobs.','danger'); return redirect(url_for('my_requests'))
    if query_db('SELECT id FROM ratings WHERE request_id=%s',(req_id,),fetchone=True):
        flash('Already rated.','info'); return redirect(url_for('my_requests'))
    if request.method=='POST':
        def _i(k):
            try: v=int(request.form.get(k,0)); return v if 1<=v<=5 else None
            except: return None
        r_p=_i('rating_punctuality'); r_q=_i('rating_quality'); r_c=_i('rating_communication')
        review=sanitize(request.form.get('review',''))
        subs=[s for s in [r_p,r_q,r_c] if s]
        overall=round(sum(subs)/3) if len(subs)==3 else _i('rating')
        if not overall or not 1<=overall<=5:
            flash('Please rate all three dimensions.','danger'); return render_template('rate.html',req=req)
        query_db("""INSERT INTO ratings (request_id,customer_id,worker_id,rating,
            rating_punctuality,rating_quality,rating_communication,review)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (req_id,uid,req['worker_id'],overall,r_p,r_q,r_c,review or None),commit=True)
        flash('Thanks for your rating! 🌟','success'); return redirect(url_for('my_requests'))
    return render_template('rate.html',req=req)

@app.route('/worker/<int:worker_id>')
def view_worker(worker_id):
    worker=query_db("""SELECT u.id,u.full_name,u.phone,u.avatar_url,wp.skills,wp.experience,
        wp.description,wp.location,wp.availability
        FROM users u JOIN worker_profiles wp ON wp.user_id=u.id
        WHERE u.id=%s AND u.role='worker'""",(worker_id,),fetchone=True)
    if not worker: flash('Not found.','danger'); return redirect(url_for('search_workers'))
    wstats=get_worker_stats(worker_id); badge=get_badge(wstats['avg_rating'],wstats['total_completed'])
    reviews=query_db("""SELECT r.rating,r.rating_punctuality,r.rating_quality,r.rating_communication,
        r.review,r.created_at,u.full_name AS customer_name,u.avatar_url AS customer_avatar
        FROM ratings r JOIN users u ON r.customer_id=u.id
        WHERE r.worker_id=%s ORDER BY r.created_at DESC LIMIT 10""",(worker_id,))
    return render_template('view_worker.html',worker=worker,wstats=wstats,badge=badge,reviews=reviews or [])

@app.route('/report/<int:reported_id>', methods=['GET','POST'])
@login_required
def report_user(reported_id):
    reporter_id=session['user_id']
    if reporter_id==reported_id: flash("Can't report yourself.",'danger'); return redirect(url_for('search_workers'))
    target=query_db('SELECT id,full_name,role FROM users WHERE id=%s AND is_admin=0',(reported_id,),fetchone=True)
    if not target: flash('User not found.','danger'); return redirect(url_for('search_workers'))
    if request.method=='POST':
        reason=sanitize(request.form.get('reason','')); details=sanitize(request.form.get('details',''))
        if not reason: flash('Select a reason.','danger'); return render_template('report.html',target=target)
        query_db('INSERT INTO reports (reporter_id,reported_id,reason,details) VALUES (%s,%s,%s,%s)',
                 (reporter_id,reported_id,reason,details or None),commit=True)
        flash('Report submitted.','success')
        return redirect(url_for('view_worker',worker_id=reported_id) if target['role']=='worker' else url_for('dashboard'))
    return render_template('report.html',target=target)

@app.route('/browse-jobs')
@login_required
@role_required('worker')
def browse_jobs():
    category=sanitize(request.args.get('category','')); location=sanitize(request.args.get('location',''))
    sql="SELECT pj.*,u.full_name as customer_name,u.phone as customer_phone FROM posted_jobs pj JOIN users u ON pj.customer_id=u.id WHERE pj.status='open'"
    params=[]
    if category: sql+=' AND pj.category=%s'; params.append(category)
    if location: sql+=' AND pj.location LIKE %s'; params.append(f'%{location}%')
    sql+=' ORDER BY pj.created_at DESC'
    return render_template('browse_jobs.html',jobs=query_db(sql,params),category=category,location=location,CATEGORIES=CATEGORIES)

@app.route('/settings', methods=['GET','POST'])
@login_required
def account_settings():
    uid=session['user_id']
    if request.method=='POST':
        action=request.form.get('action','')
        if action=='update_info':
            full_name=sanitize(request.form.get('full_name','')); email=sanitize(request.form.get('email',''))
            if not full_name: flash('Name required.','danger')
            else:
                query_db('UPDATE users SET full_name=%s,email=%s WHERE id=%s',(full_name,email or None,uid),commit=True)
                session['full_name']=full_name; flash('Updated!','success')
        elif action=='change_password':
            cur_pw=request.form.get('current_password',''); new_pw=request.form.get('new_password',''); con_pw=request.form.get('confirm_new_password','')
            user=query_db('SELECT password_hash FROM users WHERE id=%s',(uid,),fetchone=True)
            if not check_password_hash(user['password_hash'],cur_pw): flash('Wrong current password.','danger')
            elif len(new_pw)<6: flash('Too short.','danger')
            elif new_pw!=con_pw: flash("Mismatch.",'danger')
            else:
                query_db('UPDATE users SET password_hash=%s WHERE id=%s',(generate_password_hash(new_pw),uid),commit=True)
                flash('Password changed!','success')
        return redirect(url_for('account_settings'))
    user=query_db('SELECT id,full_name,phone,email,role,created_at,avatar_url FROM users WHERE id=%s',(uid,),fetchone=True)
    return render_template('settings.html',user=user)

@app.route('/job/<int:job_id>/close', methods=['POST'])
@login_required
@role_required('customer')
def close_job(job_id):
    query_db("UPDATE posted_jobs SET status='closed' WHERE id=%s AND customer_id=%s",(job_id,session['user_id']),commit=True)
    flash('Job closed.','success'); return redirect(url_for('my_posted_jobs'))

@app.route('/my-posted-jobs')
@login_required
@role_required('customer')
def my_posted_jobs():
    return render_template('my_posted_jobs.html',
        jobs=query_db('SELECT * FROM posted_jobs WHERE customer_id=%s ORDER BY created_at DESC',(session['user_id'],)))

# ── CHAT (SocketIO + File Upload) ──────────────────────────────────────────
@app.route('/chat/<int:req_id>')
@login_required
def chat(req_id):
    uid=session['user_id']
    req=query_db("""SELECT jr.*,c.full_name AS customer_name,c.phone AS customer_phone,c.avatar_url AS customer_avatar,
        w.full_name AS worker_name,w.phone AS worker_phone,w.avatar_url AS worker_avatar
        FROM job_requests jr JOIN users c ON jr.customer_id=c.id JOIN users w ON jr.worker_id=w.id
        WHERE jr.id=%s AND jr.status='accepted' AND (jr.customer_id=%s OR jr.worker_id=%s)""",(req_id,uid,uid),fetchone=True)
    if not req: flash('Chat for accepted requests only.','danger'); return redirect(url_for('dashboard'))
    messages=query_db("""SELECT cm.*,u.full_name AS sender_name,u.avatar_url AS sender_avatar
        FROM chat_messages cm JOIN users u ON cm.sender_id=u.id
        WHERE cm.request_id=%s ORDER BY cm.created_at ASC""",(req_id,))
    return render_template('chat.html',req=req,messages=messages or [])

@app.route('/chat/<int:req_id>/upload', methods=['POST'])
@login_required
def chat_upload(req_id):
    uid=session['user_id']
    req=query_db("SELECT id FROM job_requests WHERE id=%s AND status='accepted' AND (customer_id=%s OR worker_id=%s)",(req_id,uid,uid),fetchone=True)
    if not req: return jsonify({'error':'Unauthorized'}),403
    f=request.files.get('file')
    if not f or not f.filename: return jsonify({'error':'No file'}),400
    if not allowed_file(f.filename): return jsonify({'error':'File type not allowed'}),400
    f.seek(0,2); size=f.tell(); f.seek(0)
    if size > MAX_FILE_BYTES: return jsonify({'error':'File too large (max 10MB)'}),400
    ext = f.filename.rsplit('.',1)[-1].lower()
    fname = secure_filename(f"chat_{req_id}_{uid}_{int(time.time())}.{ext}")
    f.save(os.path.join(UPLOAD_FOLDER, 'chat', fname))
    file_url = f"/uploads/chat/{fname}"
    msg_type = 'image' if ext in ALLOWED_IMAGE else 'file'
    original_name = secure_filename(f.filename)
    msg_id=query_db('INSERT INTO chat_messages (request_id,sender_id,message,msg_type,file_url,file_name,file_size) VALUES (%s,%s,%s,%s,%s,%s,%s)',
                    (req_id,uid,original_name,msg_type,file_url,original_name,size),commit=True)
    sender=query_db('SELECT full_name,avatar_url FROM users WHERE id=%s',(uid,),fetchone=True)
    msg_data={
        'id':msg_id,'sender_id':uid,
        'sender_name':sender['full_name'] if sender else '',
        'sender_avatar':sender['avatar_url'] if sender else '',
        'message':original_name,'msg_type':msg_type,
        'file_url':file_url,'file_name':original_name,'file_size':size,
        'time_str':datetime.now().strftime('%I:%M %p')
    }
    socketio.emit('new_message', msg_data, room=f'chat_{req_id}')
    return jsonify({'ok':True,'msg':msg_data})

@socketio.on('join')
def on_join(data): join_room(f"chat_{data['req_id']}")

@socketio.on('leave')
def on_leave(data): leave_room(f"chat_{data['req_id']}")

@socketio.on('send_message')
def on_send_message(data):
    uid=session.get('user_id'); req_id=data.get('req_id'); message=sanitize(data.get('message',''))
    if not uid or not req_id or not message: return
    req=query_db("SELECT id FROM job_requests WHERE id=%s AND status='accepted' AND (customer_id=%s OR worker_id=%s)",
                 (req_id,uid,uid),fetchone=True)
    if not req: return
    msg_id=query_db('INSERT INTO chat_messages (request_id,sender_id,message,msg_type) VALUES (%s,%s,%s,%s)',(req_id,uid,message,'text'),commit=True)
    sender=query_db('SELECT full_name,avatar_url FROM users WHERE id=%s',(uid,),fetchone=True)
    emit('new_message',{'id':msg_id,'sender_id':uid,'sender_name':sender['full_name'] if sender else '',
                         'sender_avatar':sender.get('avatar_url','') if sender else '',
                         'message':message,'msg_type':'text',
                         'time_str':datetime.now().strftime('%I:%M %p')},room=f'chat_{req_id}')

@socketio.on('typing')
def on_typing(data):
    uid=session.get('user_id'); req_id=data.get('req_id')
    if uid and req_id: emit('user_typing',{'name':session.get('full_name',''),'uid':uid},room=f'chat_{req_id}',include_self=False)

@socketio.on('stop_typing')
def on_stop_typing(data):
    uid=session.get('user_id'); req_id=data.get('req_id')
    if uid and req_id: emit('user_stop_typing',{'uid':uid},room=f'chat_{req_id}',include_self=False)

@app.route('/api/chat/<int:req_id>/messages')
@login_required
def api_chat_messages(req_id):
    uid=session['user_id']; after_id=request.args.get('after',0,type=int)
    req=query_db("SELECT id FROM job_requests WHERE id=%s AND status='accepted' AND (customer_id=%s OR worker_id=%s)",(req_id,uid,uid),fetchone=True)
    if not req: return jsonify({'error':'Unauthorized'}),403
    messages=query_db("""SELECT cm.id,cm.sender_id,cm.message,cm.msg_type,cm.file_url,cm.file_name,cm.file_size,
        u.full_name AS sender_name,u.avatar_url AS sender_avatar,
        DATE_FORMAT(cm.created_at,'%%h:%%i %%p') AS time_str
        FROM chat_messages cm JOIN users u ON cm.sender_id=u.id
        WHERE cm.request_id=%s AND cm.id>%s ORDER BY cm.created_at ASC""",(req_id,after_id))
    return jsonify({'messages':messages or []})

@app.route('/api/check-phone')
def check_phone():
    phone=sanitize(request.args.get('phone',''))
    if not phone: return jsonify({'available':True})
    return jsonify({'available':query_db('SELECT id FROM users WHERE phone=%s',(phone,),fetchone=True) is None})

@app.errorhandler(404)
def not_found(e): return render_template('error.html',code=404,message='Page not found'),404

@app.errorhandler(500)
def server_error(e): return render_template('error.html',code=500,message='Internal server error'),500

# ═══ ADMIN ═══════════════════════════════════════════════════════════════
@app.route('/admin/setup')
def admin_setup():
    if query_db('SELECT id FROM users WHERE is_admin=1',fetchone=True):
        flash('Admin exists.','info'); return redirect(url_for('login'))
    uid=query_db('INSERT INTO users (full_name,phone,email,password_hash,role,is_admin) VALUES (%s,%s,%s,%s,%s,%s)',
                 ('Admin','0000000000','admin@localhelp.com',generate_password_hash('admin@1234'),'customer',1),commit=True)
    if uid: flash('Admin created! Phone:0000000000 Pass:admin@1234','success')
    return redirect(url_for('login'))

@app.route('/admin/')
@admin_required
def admin_dashboard():
    stats={
        'total_users':     query_db("SELECT COUNT(*) as c FROM users WHERE is_admin=0",fetchone=True)['c'],
        'total_workers':   query_db("SELECT COUNT(*) as c FROM users WHERE role='worker' AND is_admin=0",fetchone=True)['c'],
        'total_customers': query_db("SELECT COUNT(*) as c FROM users WHERE role='customer' AND is_admin=0",fetchone=True)['c'],
        'total_jobs':      query_db('SELECT COUNT(*) as c FROM job_requests',fetchone=True)['c'],
        'completed_jobs':  query_db("SELECT COUNT(*) as c FROM job_requests WHERE job_stage='completed'",fetchone=True)['c'],
        'open_posted_jobs':query_db("SELECT COUNT(*) as c FROM posted_jobs WHERE status='open'",fetchone=True)['c'],
        'total_ratings':   query_db('SELECT COUNT(*) as c FROM ratings',fetchone=True)['c'],
        'banned_users':    query_db('SELECT COUNT(*) as c FROM users WHERE is_banned=1',fetchone=True)['c'],
        'pending_reports': query_db("SELECT COUNT(*) as c FROM reports WHERE status='pending'",fetchone=True)['c'],
    }
    recent_users=query_db('SELECT id,full_name,phone,role,created_at,is_banned,avatar_url FROM users WHERE is_admin=0 ORDER BY created_at DESC LIMIT 8')
    recent_jobs=query_db("""SELECT jr.id,jr.request_code,jr.status,jr.job_stage,jr.created_at,jr.category,jr.location,
        c.full_name AS customer_name,w.full_name AS worker_name
        FROM job_requests jr JOIN users c ON jr.customer_id=c.id JOIN users w ON jr.worker_id=w.id
        ORDER BY jr.created_at DESC LIMIT 8""")
    monthly_jobs=query_db("""SELECT DATE_FORMAT(created_at,'%b %Y') AS month,
        DATE_FORMAT(created_at,'%Y-%m') AS month_key,COUNT(*) AS count
        FROM job_requests WHERE created_at>=DATE_SUB(NOW(),INTERVAL 6 MONTH)
        GROUP BY month_key,month ORDER BY month_key""")
    return render_template('admin/dashboard.html',stats=stats,recent_users=recent_users or [],
                           recent_jobs=recent_jobs or [],monthly_jobs=monthly_jobs or [])

@app.route('/admin/users')
@admin_required
def admin_users():
    search=sanitize(request.args.get('search','')); rf=request.args.get('role',''); sf=request.args.get('status','')
    sql="""SELECT u.id,u.full_name,u.phone,u.email,u.role,u.is_banned,u.created_at,u.avatar_url,
        COUNT(DISTINCT jr_c.id) AS jobs_as_customer,COUNT(DISTINCT jr_w.id) AS jobs_as_worker
        FROM users u LEFT JOIN job_requests jr_c ON jr_c.customer_id=u.id
        LEFT JOIN job_requests jr_w ON jr_w.worker_id=u.id WHERE u.is_admin=0"""
    params=[]
    if search: sql+=' AND (u.full_name LIKE %s OR u.phone LIKE %s OR u.email LIKE %s)'; params+=[f'%{search}%']*3
    if rf in ('customer','worker'): sql+=' AND u.role=%s'; params.append(rf)
    if sf=='banned': sql+=' AND u.is_banned=1'
    elif sf=='active': sql+=' AND u.is_banned=0'
    sql+=' GROUP BY u.id ORDER BY u.created_at DESC'
    return render_template('admin/users.html',users=query_db(sql,params) or [],search=search,role_filter=rf,status_filter=sf)

@app.route('/admin/user/<int:uid>')
@admin_required
def admin_user_detail(uid):
    user=query_db('SELECT * FROM users WHERE id=%s AND is_admin=0',(uid,),fetchone=True)
    if not user: flash('Not found.','danger'); return redirect(url_for('admin_users'))
    profile=query_db('SELECT * FROM worker_profiles WHERE user_id=%s',(uid,),fetchone=True) if user['role']=='worker' else None
    wstats=get_worker_stats(uid) if user['role']=='worker' else None
    jobs=query_db("""SELECT jr.id,jr.request_code,jr.status,jr.job_stage,jr.category,jr.location,jr.created_at,
        c.full_name AS customer_name,w.full_name AS worker_name
        FROM job_requests jr JOIN users c ON jr.customer_id=c.id JOIN users w ON jr.worker_id=w.id
        WHERE jr.customer_id=%s OR jr.worker_id=%s ORDER BY jr.created_at DESC LIMIT 20""",(uid,uid))
    reviews=query_db("""SELECT r.rating,r.review,r.created_at,c.full_name AS customer_name
        FROM ratings r JOIN users c ON r.customer_id=c.id
        WHERE r.worker_id=%s ORDER BY r.created_at DESC LIMIT 10""",(uid,)) if user['role']=='worker' else []
    return render_template('admin/user_detail.html',user=user,profile=profile,wstats=wstats,jobs=jobs or [],reviews=reviews or [])

@app.route('/admin/user/<int:uid>/ban', methods=['POST'])
@admin_required
def admin_ban_user(uid):
    action=request.form.get('action','')
    user=query_db('SELECT id,full_name,is_banned FROM users WHERE id=%s AND is_admin=0',(uid,),fetchone=True)
    if not user: flash('Not found.','danger'); return redirect(url_for('admin_users'))
    if action=='ban': query_db('UPDATE users SET is_banned=1 WHERE id=%s',(uid,),commit=True); flash(f"{user['full_name']} banned.",'warning')
    elif action=='unban': query_db('UPDATE users SET is_banned=0 WHERE id=%s',(uid,),commit=True); flash(f"{user['full_name']} unbanned.",'success')
    return redirect(url_for('admin_user_detail',uid=uid))

@app.route('/admin/user/<int:uid>/delete', methods=['POST'])
@admin_required
def admin_delete_user(uid):
    user=query_db('SELECT full_name FROM users WHERE id=%s AND is_admin=0',(uid,),fetchone=True)
    if not user: flash('Not found.','danger'); return redirect(url_for('admin_users'))
    query_db('DELETE FROM users WHERE id=%s',(uid,),commit=True); flash(f"Deleted {user['full_name']}.",'success'); return redirect(url_for('admin_users'))

@app.route('/admin/jobs')
@admin_required
def admin_jobs():
    sf=request.args.get('status',''); stf=request.args.get('stage',''); search=sanitize(request.args.get('search',''))
    sql="""SELECT jr.id,jr.request_code,jr.status,jr.job_stage,jr.category,jr.location,jr.description,jr.created_at,jr.scheduled_at,
        c.full_name AS customer_name,c.phone AS customer_phone,w.full_name AS worker_name,w.phone AS worker_phone
        FROM job_requests jr JOIN users c ON jr.customer_id=c.id JOIN users w ON jr.worker_id=w.id WHERE 1=1"""
    params=[]
    if sf in ('pending','accepted','rejected'): sql+=' AND jr.status=%s'; params.append(sf)
    if stf in ('accepted','on_the_way','arrived','in_progress','completed'): sql+=' AND jr.job_stage=%s'; params.append(stf)
    if search: sql+=' AND (c.full_name LIKE %s OR w.full_name LIKE %s OR jr.category LIKE %s OR jr.request_code LIKE %s)'; params+=[f'%{search}%']*4
    sql+=' ORDER BY jr.created_at DESC'
    return render_template('admin/jobs.html',jobs=query_db(sql,params) or [],status_filter=sf,stage_filter=stf,search=search,STAGE_LABELS=STAGE_LABELS)

@app.route('/admin/posted-jobs')
@admin_required
def admin_posted_jobs():
    sf=request.args.get('status','')
    sql="SELECT pj.*,u.full_name AS customer_name,u.phone AS customer_phone FROM posted_jobs pj JOIN users u ON pj.customer_id=u.id WHERE 1=1"
    params=[]
    if sf in ('open','closed'): sql+=' AND pj.status=%s'; params.append(sf)
    sql+=' ORDER BY pj.created_at DESC'
    return render_template('admin/posted_jobs.html',jobs=query_db(sql,params) or [],status_filter=sf)

@app.route('/admin/ratings')
@admin_required
def admin_ratings():
    ratings=query_db("""SELECT r.id,r.rating,r.rating_punctuality,r.rating_quality,r.rating_communication,
        r.review,r.created_at,c.full_name AS customer_name,w.full_name AS worker_name,jr.category,jr.location,jr.request_code
        FROM ratings r JOIN users c ON r.customer_id=c.id JOIN users w ON r.worker_id=w.id
        JOIN job_requests jr ON r.request_id=jr.id ORDER BY r.created_at DESC""")
    return render_template('admin/ratings.html',ratings=ratings or [])

@app.route('/admin/reports')
@admin_required
def admin_reports():
    sf=request.args.get('status','pending')
    sql="""SELECT rp.id,rp.reason,rp.details,rp.status,rp.created_at,
        reporter.full_name AS reporter_name,reporter.phone AS reporter_phone,
        reported.full_name AS reported_name,reported.phone AS reported_phone,
        reported.id AS reported_id,reported.is_banned
        FROM reports rp JOIN users reporter ON rp.reporter_id=reporter.id
        JOIN users reported ON rp.reported_id=reported.id"""
    params=[]
    if sf in ('pending','reviewed','dismissed'): sql+=' WHERE rp.status=%s'; params.append(sf)
    sql+=' ORDER BY rp.created_at DESC'
    pending_count=query_db("SELECT COUNT(*) as c FROM reports WHERE status='pending'",fetchone=True)['c']
    return render_template('admin/reports.html',reports=query_db(sql,params) or [],status_filter=sf,pending_count=pending_count)

@app.route('/admin/reports/<int:report_id>/action', methods=['POST'])
@admin_required
def admin_report_action(report_id):
    action=request.form.get('action','')
    report=query_db('SELECT * FROM reports WHERE id=%s',(report_id,),fetchone=True)
    if not report: flash('Not found.','danger'); return redirect(url_for('admin_reports'))
    if action=='approve':
        query_db("UPDATE reports SET status='reviewed' WHERE id=%s",(report_id,),commit=True)
        query_db('UPDATE users SET is_banned=1 WHERE id=%s',(report['reported_id'],),commit=True)
        flash('Report approved — user banned.','warning')
    elif action=='dismiss':
        query_db("UPDATE reports SET status='dismissed' WHERE id=%s",(report_id,),commit=True)
        flash('Report dismissed.','info')
    return redirect(url_for('admin_reports'))

@app.route('/admin/geocode-backfill', methods=['POST'])
@admin_required
def admin_geocode_backfill():
    rows=query_db("SELECT user_id,location FROM worker_profiles WHERE location IS NOT NULL AND location!='' AND (lat IS NULL OR lng IS NULL)") or []
    updated=failed=0
    for row in rows:
        lat,lng=geocode_location(row['location'])
        if lat and lng: query_db('UPDATE worker_profiles SET lat=%s,lng=%s WHERE user_id=%s',(lat,lng,row['user_id']),commit=True); updated+=1
        else: failed+=1
        time.sleep(1.1)
    flash(f'Geocoding done — {updated} updated, {failed} failed.','success'); return redirect(url_for('admin_dashboard'))

if __name__ == '__main__':
    try: 
        #init_db()
        pass
    except Exception as ex: print(f'[WARNING] DB init: {ex}')
    port = int(os.environ.get('PORT', 5000))
    import socket
    for p in range(port, port + 10):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('localhost', p)) != 0:
                port = p
                break
    print(f'[LHC] Starting on http://localhost:{port}')
    socketio.run(app, debug=True, host='0.0.0.0', port=port, use_reloader=False, allow_unsafe_werkzeug=True)