def test_login_returns_bearer_token(client, user):
    response = client.post("/login", json={"email": user["email"], "password": user["password"]})
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert len(body["access_token"]) > 20


def test_login_rejects_wrong_password(client, user):
    response = client.post("/login", json={"email": user["email"], "password": "not-the-password"})
    assert response.status_code == 401
