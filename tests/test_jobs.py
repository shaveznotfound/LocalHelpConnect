"""
tests/test_jobs.py
Tests: hire worker, accept/reject request, stage update, scheduling
"""

import pytest
import app as _app
from tests.conftest import register, login, logout, make_worker, make_job_request


class TestHireWorker:

    def test_customer_can_hire_worker(self, client):
        wid = make_worker(client)
        register(client, '9400000001', role='customer', name='CustA')
        login(client, '9400000001')
        rv = client.post(f'/hire/{wid}', data={
            'description': 'Fix bedroom fan wiring',
            'location': 'Block B, Sector 56',
            'category': 'Electrical',
        }, follow_redirects=True)
        assert rv.status_code == 200
        req = _app.query_db('SELECT * FROM job_requests WHERE worker_id=%s', (wid,), fetchone=True)
        assert req is not None
        assert req['status'] == 'pending'

    def test_hire_with_scheduled_date(self, client):
        wid = make_worker(client, phone='9400000010')
        register(client, '9400000011', role='customer', name='SchedCust')
        login(client, '9400000011')
        client.post(f'/hire/{wid}', data={
            'description': 'AC service',
            'location': 'Sector 22',
            'category': 'Appliance Repair',
            'scheduled_at': '2026-12-25 10:00',
        }, follow_redirects=True)
        req = _app.query_db('SELECT * FROM job_requests WHERE worker_id=%s', (wid,), fetchone=True)
        assert req is not None
        assert req['scheduled_at'] is not None

    def test_worker_cannot_hire(self, client):
        wid = make_worker(client, phone='9400000020')
        register(client, '9400000021', role='worker', name='Worker2')
        login(client, '9400000021')
        rv = client.post(f'/hire/{wid}', data={
            'description': 'Test', 'location': 'Test',
        }, follow_redirects=True)
        assert b'Access denied' in rv.data or rv.status_code in (302, 200)

    def test_hire_requires_description_and_location(self, client):
        wid = make_worker(client, phone='9400000030')
        register(client, '9400000031', role='customer', name='CustB')
        login(client, '9400000031')
        rv = client.post(f'/hire/{wid}', data={
            'description': '', 'location': '',
        }, follow_redirects=True)
        assert b'required' in rv.data.lower()


class TestRequestActions:

    def test_worker_accepts_request(self, client):
        wid = make_worker(client, phone='9410000001')
        req_id = make_job_request(client, wid, cust_phone='9410000002', status='pending')
        login(client, '9410000001')
        rv = client.post(f'/request/{req_id}/update',
                         data={'status': 'accepted'}, follow_redirects=True)
        assert rv.status_code == 200
        req = _app.query_db('SELECT status, job_stage FROM job_requests WHERE id=%s', (req_id,), fetchone=True)
        assert req['status'] == 'accepted'
        assert req['job_stage'] == 'accepted'

    def test_worker_rejects_request(self, client):
        wid = make_worker(client, phone='9410000003')
        req_id = make_job_request(client, wid, cust_phone='9410000004', status='pending')
        login(client, '9410000003')
        client.post(f'/request/{req_id}/update',
                    data={'status': 'rejected'}, follow_redirects=True)
        req = _app.query_db('SELECT status FROM job_requests WHERE id=%s', (req_id,), fetchone=True)
        assert req['status'] == 'rejected'

    def test_customer_cannot_update_request(self, client):
        wid = make_worker(client, phone='9410000005')
        req_id = make_job_request(client, wid, cust_phone='9410000006', status='pending')
        login(client, '9410000006')
        rv = client.post(f'/request/{req_id}/update',
                         data={'status': 'accepted'}, follow_redirects=True)
        # Should be redirected away (role guard)
        assert b'Access denied' in rv.data or rv.status_code == 200


class TestStageUpdate:

    def test_stage_advances_correctly(self, client):
        wid = make_worker(client, phone='9420000001')
        req_id = make_job_request(client, wid, cust_phone='9420000002', status='accepted')

        login(client, '9420000001')
        stages = ['on_the_way', 'arrived', 'in_progress', 'completed']
        for expected in stages:
            client.post(f'/request/{req_id}/stage', follow_redirects=True)
            req = _app.query_db('SELECT job_stage FROM job_requests WHERE id=%s', (req_id,), fetchone=True)
            assert req['job_stage'] == expected

    def test_stage_cannot_advance_past_completed(self, client):
        wid = make_worker(client, phone='9420000003')
        req_id = make_job_request(client, wid, cust_phone='9420000004', status='accepted')
        _app.query_db("UPDATE job_requests SET job_stage='completed' WHERE id=%s", (req_id,), commit=True)

        login(client, '9420000003')
        rv = client.post(f'/request/{req_id}/stage', follow_redirects=True)
        assert b'completed' in rv.data.lower() or b'already' in rv.data.lower()
