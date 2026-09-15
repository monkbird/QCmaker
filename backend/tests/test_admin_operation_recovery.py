from backend.app.api.endpoints.admin.data import recover_interrupted_admin_operations
from backend.app.repositories.database import init_database
from backend.app.services.admin_operations import begin_operation, get_operation, mark_operation_running


def test_startup_marks_interrupted_intents_without_replaying_actions(isolated_storage):
    init_database()
    pending = begin_operation(actor_id='u', actor_name='admin', kind='dataset_delete', scope='dataset-a', intended={'dataset_id': 'dataset-a'}, request_id='pending-test', idempotency_key='pending-test')
    running = begin_operation(actor_id='u', actor_name='admin', kind='llm_probe', scope='openai/test', intended={'provider': 'openai', 'model': 'test'}, request_id='running-test', idempotency_key='running-test')
    mark_operation_running(running.operation_id)
    assert recover_interrupted_admin_operations() == {'interrupted': 2}
    assert get_operation(pending.operation_id).state == 'failed'
    assert get_operation(pending.operation_id).retryable
    assert get_operation(running.operation_id).state == 'failed'
    assert not get_operation(running.operation_id).retryable
    assert recover_interrupted_admin_operations() == {'interrupted': 0}
