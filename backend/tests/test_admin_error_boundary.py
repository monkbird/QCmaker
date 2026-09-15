from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from backend.app.core.errors import install_error_handlers


def test_validation_never_echoes_secret_and_bounds_request_id():
    app = FastAPI()

    class Payload(BaseModel):
        password: str = Field(max_length=3)

    @app.post('/api/admin/check')
    def check(payload: Payload):
        return {}

    install_error_handlers(app)
    with TestClient(app) as client:
        response = client.post('/api/admin/check', json={'password': 'sensitive-secret'}, headers={'x-request-id': 'x' * 200})
    assert response.status_code == 422
    assert 'sensitive-secret' not in response.text
    assert response.headers['Cache-Control'] == 'no-store'
    assert response.headers['x-request-id'].startswith('req_')
