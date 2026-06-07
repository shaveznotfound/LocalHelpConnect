"""
tests/test_admin.py
Tests: admin access control, ban/unban, report approve/dismiss
"""

import pytest
import app as _app
from tests.conftest import register, login, logout, make_worker, make_job_request


def make_admin(client):
    """Create admin account via /admin/setup and login."""
    client.get('/admin/setup', follow_redirects=True)
    client.post('/login', data={'phone': '0000000000', 'password': 'admin@1234'},
                follow_redirects=True)


class TestAdminAccess:

    def test_admin_dashboard_requires_admin(self, client):
        register(client, '9600000001', role='customer')
        login(client, '9600000001')
        rv = client.get('/admin/', follow_redirects=True)
        assert b'Admin' not in rv.data or b'Access denied' in rv.data or b'required' in rv.data

    def test_unauthenticated_cannot_access_admin(self, client):
        rv = client.get('/admin/', follow_redirects=True)
        assert b'login' in rv.data.lower() or b'Login' in rv.data

    def test_admin_can_access_dashboard(self, client):
        make_admin(client)
        rv = client.get('/admin/')
        assert rv.status_code == 200
        assert b'Dashboard' in rv.data

    def test_admin_can_view_users(self, client):
        make_admin(client)
        rv = client.get('/admin/users')
        assert rv.status_code == 200

    def test_admin_can_view_reports(self, client):
        make_admin(client)
        rv = client.get('/admin/reports')
        assert rv.status_code == 200


class TestBanUnban:

    def test_admin_can_ban_user(self, client):
        register(client, '9610000001', role='customer', name='BanMe')
        user = _app.query_db('SELECT id FROM users WHERE phone=%s', ('9610000001',), fetchone=True)
        uid = user['id']

        make_admin(client)
        rv = client.post(f'/admin/user/{uid}/ban', data={'action': 'ban'}, follow_redirects=True)
        assert rv.status_code == 200
        u = _app.query_db('SELECT is_banned FROM users WHERE id=%s', (uid,), fetchone=True)
        assert u['is_banned'] == 1

    def test_admin_can_unban_user(self, client):
        register(client, '9610000002', role='customer', name='UnbanMe')
        user = _app.query_db('SELECT id FROM users WHERE phone=%s', ('9610000002',), fetchone=True)
        uid = user['id']
        _app.query_db('UPDATE users SET is_banned=1 WHERE id=%s', (uid,), commit=True)

        make_admin(client)
        client.post(f'/admin/user/{uid}/ban', data={'action': 'unban'}, follow_redirects=True)
        u = _app.query_db('SELECT is_banned FROM users WHERE id=%s', (uid,), fetchone=True)
        assert u['is_banned'] == 0

    def test_banned_user_cannot_login(self, client):
        register(client, '9610000003', role='customer')
        user = _app.query_db('SELECT id FROM users WHERE phone=%s', ('9610000003',), fetchone=True)
        _app.query_db('UPDATE users SET is_banned=1 WHERE id=%s', (user['id'],), commit=True)

        rv = client.post('/login', data={'phone': '9610000003', 'password': 'Test@1234'},
                         follow_redirects=True)
        assert b'banned' in rv.data.lower()


class TestReportSystem:

    def test_customer_can_report_worker(self, client):
        wid = make_worker(client, phone='9620000001')
        register(client, '9620000002', role='customer', name='Reporter')
        login(client, '9620000002')
        rv = client.post(f'/report/{wid}', data={
            'reason': 'No-show / job abandonment',
            'details': 'Worker never showed up.',
        }, follow_redirects=True)
        assert rv.status_code == 200
        report = _app.query_db('SELECT * FROM reports WHERE reported_id=%s', (wid,), fetchone=True)
        assert report is not None
        assert report['status'] == 'pending'

    def test_admin_approve_report_bans_user(self, client):
        wid = make_worker(client, phone='9620000003')
        register(client, '9620000004', role='customer')
        login(client, '9620000004')
        client.post(f'/report/{wid}', data={'reason': 'Fraud or overcharging'}, follow_redirects=True)
        logout(client)

        report = _app.query_db('SELECT id FROM reports WHERE reported_id=%s', (wid,), fetchone=True)

        make_admin(client)
        client.post(f'/admin/reports/{report["id"]}/action',
                    data={'action': 'approve'}, follow_redirects=True)

        user = _app.query_db('SELECT is_banned FROM users WHERE id=%s', (wid,), fetchone=True)
        assert user['is_banned'] == 1
        rp = _app.query_db('SELECT status FROM reports WHERE id=%s', (report["id"],), fetchone=True)
        assert rp['status'] == 'reviewed'

    def test_admin_dismiss_report(self, client):
        wid = make_worker(client, phone='9620000005')
        register(client, '9620000006', role='customer')
        login(client, '9620000006')
        client.post(f'/report/{wid}', data={'reason': 'Spam or irrelevant contact'}, follow_redirects=True)
        logout(client)

        report = _app.query_db('SELECT id FROM reports WHERE reported_id=%s', (wid,), fetchone=True)
        make_admin(client)
        client.post(f'/admin/reports/{report["id"]}/action',
                    data={'action': 'dismiss'}, follow_redirects=True)

        rp = _app.query_db('SELECT status FROM reports WHERE id=%s', (report["id"],), fetchone=True)
        assert rp['status'] == 'dismissed'
        # User should NOT be banned on dismiss
        user = _app.query_db('SELECT is_banned FROM users WHERE id=%s', (wid,), fetchone=True)
        assert user['is_banned'] == 0

    def test_user_cannot_report_themselves(self, client):
        register(client, '9620000007', role='customer', name='Self')
        user = _app.query_db('SELECT id FROM users WHERE phone=%s', ('9620000007',), fetchone=True)
        login(client, '9620000007')
        rv = client.post(f'/report/{user["id"]}', data={'reason': 'Other'}, follow_redirects=True)
        assert b"can" in rv.data.lower() or b"yourself" in rv.data.lower()
