import pytest
from fastapi import status

from tests.utils.database import insert_test_data_transactional


@pytest.fixture
def client(txn_api_logged_in):
    test_client, session = txn_api_logged_in
    insert_test_data_transactional(session, 'habitcategories')
    return test_client


def current_habit(client):
    return next(h for h in client.get('/habits').json() if h['is_current'])


def board_for(client, habit_id):
    board = client.get('/habits/day').json()
    done = any(c['habit_id'] == habit_id for c in board['completed'])
    checklist = next(c for c in board['checklists'] if c['habit_id'] == habit_id)
    return done, checklist


def test_the_tick_that_fills_every_item_completes_the_habit(client):
    habit = current_habit(client)
    squat = client.post(f'/habits/{habit["id"]}/items', json={'name': 'Squat', 'daily_target': 2}).json()
    lunge = client.post(f'/habits/{habit["id"]}/items', json={'name': 'Lunge', 'daily_target': 1}).json()

    for item in (squat, squat):
        assert client.post(f'/habits/items/{item["id"]}/ticks', json={}).status_code == status.HTTP_201_CREATED
    done, checklist = board_for(client, habit['id'])
    assert not done
    assert [i['done'] for i in checklist['items']] == [True, False]

    answered = client.post(f'/habits/items/{lunge["id"]}/ticks', json={}).json()
    assert answered['complete']
    done, _ = board_for(client, habit['id'])
    assert done
    assert habit['id'] not in [h['id'] for h in client.get('/habits/day').json()['due']]


def test_an_untick_below_target_takes_the_completion_back(client):
    habit = current_habit(client)
    item = client.post(f'/habits/{habit["id"]}/items', json={'name': 'Push-up', 'daily_target': 1}).json()
    checklist = client.post(f'/habits/items/{item["id"]}/ticks', json={}).json()
    tick_id = checklist['items'][0]['ticks'][0]['id']
    assert board_for(client, habit['id'])[0]

    response = client.delete(f'/habits/items/{item["id"]}/ticks/{tick_id}')
    assert response.status_code == status.HTTP_200_OK
    assert not response.json()['complete']
    done, checklist = board_for(client, habit['id'])
    assert not done
    assert checklist['items'][0]['ticks'] == []
