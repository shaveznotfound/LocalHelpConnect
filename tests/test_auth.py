"""
tests/test_auth.py
Tests: register, login, logout, duplicate phone, account locking
"""

import pytest
from tests.conftest import register, login, logout
import app as _app


class TestRegister:

    def test_register_customer_success(self, client):
        rv = register(client, '9111000001', role='customer', name='Alice')
        assert rv.status_code == 200
        user = _app.query_db('SELECT * FROM users WHERE phone=%s', ('9111000001',), fetchone=True)
        assert user is not None
        assert user['full_name'] == 'Alice'
        assert user['role'] == 'customer'

    def test_register_worker_creates_profile(self, client):
        register(client, '9111000002', role='worker', name='Bob')
        profile = _app.query_db(
            'SELECT wp.id FROM worker_profiles wp JOIN users u ON wp.user_id=u.id WHERE u.phone=%s',
            ('9111000002',), fetchone=True)
        assert profile is not None

    def test_register_duplicate_phone_rejected(self, client):
        register(client, '9111000003', role='customer')
        rv = register(client, '9111000003', role='worker')
        assert b'already registered' in rv.data

    def test_register_password_mismatch(self, client):
        rv = client.post('/register', data={
            'full_name': 'Eve', 'phone': '9111000004',
            'password': 'abc123', 'confirm_password': 'xyz999',
            'role': 'customer',
        }, follow_redirects=True)
        assert b'mismatch' in rv.data.lower() or b'do not match' in rv.data.lower()

    def test_register_short_password(self, client):
        rv = client.post('/register', data={
            'full_name': 'Eve', 'phone': '9111000005',
            'password': 'abc', 'confirm_password': 'abc',
            'role': 'customer',
        }, follow_redirects=True)
        assert b'6 char' in rv.data.lower() or b'least 6' in rv.data.lower()


class TestLogin:

    def test_login_success(self, client):
        register(client, '9222000001', name='Carol')
        rv = login(client, '9222000001')
        assert b'Welcome' in rv.data

    def test_login_wrong_password(self, client):
        register(client, '9222000002')
        rv = client.post('/login', data={'phone': '9222000002', 'password': 'WRONG'},
                         follow_redirects=True)
        assert rv.status_code == 200
        assert b'Invalid' in rv.data or b'Wrong' in rv.data or b'left' in rv.data

    def test_login_nonexistent_phone(self, client):
        rv = client.post('/login', data={'phone': '0000000000', 'password': 'anything'},
                         follow_redirects=True)
        assert b'Invalid' in rv.data or b'credentials' in rv.data.lower()

    def test_login_banned_user(self, client):
        register(client, '9222000003')
        user = _app.query_db('SELECT id FROM users WHERE phone=%s', ('9222000003',), fetchone=True)
        _app.query_db('UPDATE users SET is_banned=1 WHERE id=%s', (user['id'],), commit=True)
        rv = client.post('/login', data={'phone': '9222000003', 'password': 'Test@1234'},
                         follow_redirects=True)
        assert b'banned' in rv.data.lower()

    def test_account_locked_after_5_failures(self, client):
        register(client, '9222000004')
        for _ in range(5):
            client.post('/login', data={'phone': '9222000004', 'password': 'WRONG'},
                        follow_redirects=True)
        rv = client.post('/login', data={'phone': '9222000004', 'password': 'WRONG'},
                         follow_redirects=True)
        assert b'locked' in rv.data.lower() or b'locked' in rv.data.lower()


class TestLogout:

    def test_logout_redirects_to_index(self, client):
        register(client, '9333000001')
        login(client, '9333000001')
        rv = client.get('/logout', follow_redirects=True)
        assert rv.status_code == 200

    def test_logout_clears_session(self, client):
        register(client, '9333000002')
        login(client, '9333000002')
        logout(client)
        rv = client.get('/dashboard', follow_redirects=True)
        assert b'login' in rv.data.lower() or b'Login' in rv.data
