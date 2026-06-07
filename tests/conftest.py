"""
conftest.py — pytest fixtures for Local Help Connect v5
Uses a separate test database: lhc_v5_test
All tests run against this DB; production data is never touched.
"""

import os
import sys
import pytest

# Make the project root importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Point at the test DB before importing app
os.environ['DB_NAME'] = 'lhc_v5_test'

import app as _app_module


@pytest.fixture(scope='session')
def app():
    """Create and configure the Flask app for testing."""
    _app_module.app.config.update({
        'TESTING': True,
        'SECRET_KEY': 'test-secret-key',
        'WTF_CSRF_ENABLED': False,
    })
    # Initialise the test database (creates tables if missing)
    try:
        _app_module.init_db()
    except Exception as e:
        pytest.skip(f'DB unavailable: {e}')
    yield _app_module.app


@pytest.fixture(scope='session')
def client(app):
    """Flask test client (session-scoped — shared across all tests)."""
    return app.test_client()


@pytest.fixture(autouse=True)
def clean_db(app):
    """
    Wipe user-generated data before every test so tests are independent.
    Order matters: child tables before parent.
    """
    with app.app_context():
        tables = [
            'reports', 'ratings', 'chat_messages',
            'job_requests', 'posted_jobs',
            'worker_availability', 'worker_profiles',
            'users',
        ]
        for t in tables:
            _app_module.query_db(f'DELETE FROM {t}', commit=True)
    yield


# ─── Convenience helpers ────────────────────────────────────────────────────────

def register(client, phone, password='Test@1234', role='customer', name='Test User'):
    return client.post('/register', data={
        'full_name': name, 'phone': phone,
        'email': f'{phone}@test.com',
        'password': password, 'confirm_password': password,
        'role': role,
    }, follow_redirects=True)


def login(client, phone, password='Test@1234'):
    return client.post('/login', data={'phone': phone, 'password': password},
                       follow_redirects=True)


def logout(client):
    return client.get('/logout', follow_redirects=True)


def make_worker(client, phone='9000000002', name='Test Worker'):
    register(client, phone, role='worker', name=name)
    # Give them a profile
    login(client, phone)
    client.post('/profile', data={
        'skills': 'Electrical, Wiring',
        'experience': '3 years',
        'description': 'Test worker description',
        'location': 'Gurugram',
        'availability': 'available',
    }, follow_redirects=True)
    logout(client)
    wid = _app_module.query_db('SELECT id FROM users WHERE phone=%s', (phone,), fetchone=True)
    return wid['id'] if wid else None


def make_job_request(client, worker_id, cust_phone='9000000001', status='accepted'):
    """Register customer, hire worker, optionally accept the request."""
    register(client, cust_phone, role='customer', name='Test Customer')
    login(client, cust_phone)
    client.post(f'/hire/{worker_id}', data={
        'description': 'Fix the fan wiring',
        'location': 'Sector 14 Gurugram',
        'category': 'Electrical',
    }, follow_redirects=True)
    logout(client)

    req = _app_module.query_db(
        'SELECT id FROM job_requests WHERE worker_id=%s ORDER BY created_at DESC LIMIT 1',
        (worker_id,), fetchone=True)
    req_id = req['id'] if req else None

    if status == 'accepted' and req_id:
        _app_module.query_db(
            "UPDATE job_requests SET status='accepted', job_stage='accepted', stage_updated_at=NOW() WHERE id=%s",
            (req_id,), commit=True)

    return req_id
