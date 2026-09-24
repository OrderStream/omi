"""Unit tests for shared action items acceptance endpoints."""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

import routers.action_items as action_items
from routers.action_items import AcceptSharedTasksRequest, accept_shared_action_items


@pytest.fixture
def accept_request():
    return AcceptSharedTasksRequest(token='test-token-uuid')


@pytest.fixture
def share_data():
    return {'uid': 'sender-user-123', 'display_name': 'Alice', 'task_ids': ['task-1', 'task-2']}


def test_accept_shared_tasks_all_deleted_returns_404(accept_request, share_data, monkeypatch):
    mock_redis = MagicMock()
    mock_redis.get_task_share.return_value = share_data
    mock_db = MagicMock()
    mock_db.get_action_item.return_value = None
    mock_wake = MagicMock()
    monkeypatch.setattr(action_items, 'redis_db', mock_redis)
    monkeypatch.setattr(action_items, 'action_items_db', mock_db)
    monkeypatch.setattr(action_items, '_wake_task_changes', mock_wake)

    with pytest.raises(HTTPException) as exc_info:
        accept_shared_action_items(accept_request, uid='recipient-user-456')

    assert exc_info.value.status_code == 404
    assert 'deleted or not found' in exc_info.value.detail
    mock_redis.try_accept_task_share.assert_not_called()
    mock_wake.assert_not_called()


def test_accept_shared_tasks_all_locked_returns_402(accept_request, share_data, monkeypatch):
    mock_redis = MagicMock()
    mock_redis.get_task_share.return_value = share_data
    mock_db = MagicMock()
    mock_db.get_action_item.side_effect = lambda uid, task_id: {'id': task_id, 'is_locked': True}
    mock_wake = MagicMock()
    monkeypatch.setattr(action_items, 'redis_db', mock_redis)
    monkeypatch.setattr(action_items, 'action_items_db', mock_db)
    monkeypatch.setattr(action_items, '_wake_task_changes', mock_wake)

    with pytest.raises(HTTPException) as exc_info:
        accept_shared_action_items(accept_request, uid='recipient-user-456')

    assert exc_info.value.status_code == 402
    assert 'locked' in exc_info.value.detail
    mock_redis.try_accept_task_share.assert_not_called()
    mock_wake.assert_not_called()


def test_accept_shared_tasks_create_failure_rolls_back_token(accept_request, share_data, monkeypatch):
    mock_redis = MagicMock()
    mock_redis.get_task_share.return_value = share_data
    mock_redis.try_accept_task_share.return_value = True
    mock_db = MagicMock()
    eligible_item = {'id': 'task-1', 'description': 'Do homework', 'is_locked': False, 'due_at': None}
    mock_db.get_action_item.side_effect = lambda uid, task_id: eligible_item if task_id == 'task-1' else None
    mock_db.create_action_item.side_effect = RuntimeError('Database down')
    mock_vector = MagicMock()
    mock_wake = MagicMock()
    monkeypatch.setattr(action_items, 'redis_db', mock_redis)
    monkeypatch.setattr(action_items, 'action_items_db', mock_db)
    monkeypatch.setattr(action_items, 'upsert_action_item_vector', mock_vector)
    monkeypatch.setattr(action_items, '_wake_task_changes', mock_wake)

    with pytest.raises(RuntimeError, match='Database down'):
        accept_shared_action_items(accept_request, uid='recipient-user-456')

    mock_redis.undo_accept_task_share.assert_called_once_with('test-token-uuid', 'recipient-user-456')
    mock_wake.assert_not_called()
