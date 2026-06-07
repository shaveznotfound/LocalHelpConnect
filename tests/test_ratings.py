"""
tests/test_ratings.py
Tests: submit 3-dimension rating, duplicate rating blocked, only completed jobs
"""

import pytest
import app as _app
from tests.conftest import register, login, logout, make_worker, make_job_request


def complete_job(req_id):
    """Force a job request to completed stage directly via DB."""
    _app.query_db(
        "UPDATE job_requests SET status='accepted', job_stage='completed', stage_updated_at=NOW() WHERE id=%s",
        (req_id,), commit=True)


class TestRatingSubmission:

    def test_submit_rating_with_all_dimensions(self, client):
        wid = make_worker(client, phone='9500000001')
        req_id = make_job_request(client, wid, cust_phone='9500000002')
        complete_job(req_id)

        login(client, '9500000002')
        rv = client.post(f'/rate/{req_id}', data={
            'rating_punctuality':   '5',
            'rating_quality':       '4',
            'rating_communication': '5',
            'review': 'Excellent work!',
        }, follow_redirects=True)
        assert rv.status_code == 200

        rating = _app.query_db('SELECT * FROM ratings WHERE request_id=%s', (req_id,), fetchone=True)
        assert rating is not None
        assert rating['rating_punctuality'] == 5
        assert rating['rating_quality'] == 4
        assert rating['rating_communication'] == 5
        # Overall should be average = round((5+4+5)/3) = 5
        assert rating['rating'] == 5

    def test_overall_rating_is_average_of_dimensions(self, client):
        wid = make_worker(client, phone='9500000003')
        req_id = make_job_request(client, wid, cust_phone='9500000004')
        complete_job(req_id)

        login(client, '9500000004')
        client.post(f'/rate/{req_id}', data={
            'rating_punctuality':   '2',
            'rating_quality':       '4',
            'rating_communication': '3',
            'review': '',
        }, follow_redirects=True)
        rating = _app.query_db('SELECT rating FROM ratings WHERE request_id=%s', (req_id,), fetchone=True)
        # average = (2+4+3)/3 = 3.0 → rounded = 3
        assert rating['rating'] == 3

    def test_duplicate_rating_blocked(self, client):
        wid = make_worker(client, phone='9500000005')
        req_id = make_job_request(client, wid, cust_phone='9500000006')
        complete_job(req_id)

        login(client, '9500000006')
        # First rating
        client.post(f'/rate/{req_id}', data={
            'rating_punctuality': '5', 'rating_quality': '5',
            'rating_communication': '5', 'review': 'First',
        }, follow_redirects=True)
        # Second rating attempt
        rv = client.post(f'/rate/{req_id}', data={
            'rating_punctuality': '1', 'rating_quality': '1',
            'rating_communication': '1', 'review': 'Second',
        }, follow_redirects=True)
        assert b'already rated' in rv.data.lower() or b'Already' in rv.data

        # Only one rating should exist
        count = _app.query_db('SELECT COUNT(*) as c FROM ratings WHERE request_id=%s', (req_id,), fetchone=True)
        assert count['c'] == 1

    def test_cannot_rate_pending_job(self, client):
        wid = make_worker(client, phone='9500000007')
        req_id = make_job_request(client, wid, cust_phone='9500000008', status='pending')

        login(client, '9500000008')
        rv = client.post(f'/rate/{req_id}', data={
            'rating_punctuality': '5', 'rating_quality': '5',
            'rating_communication': '5',
        }, follow_redirects=True)
        # Should be redirected — only completed jobs can be rated
        count = _app.query_db('SELECT COUNT(*) as c FROM ratings WHERE request_id=%s', (req_id,), fetchone=True)
        assert count['c'] == 0

    def test_worker_stats_reflect_sub_scores(self, client):
        wid = make_worker(client, phone='9500000009')
        req_id = make_job_request(client, wid, cust_phone='9500000010')
        complete_job(req_id)

        login(client, '9500000010')
        client.post(f'/rate/{req_id}', data={
            'rating_punctuality': '4', 'rating_quality': '5',
            'rating_communication': '3', 'review': '',
        }, follow_redirects=True)

        stats = _app.get_worker_stats(wid)
        assert stats['avg_punctuality'] == 4.0
        assert stats['avg_quality'] == 5.0
        assert stats['avg_communication'] == 3.0
