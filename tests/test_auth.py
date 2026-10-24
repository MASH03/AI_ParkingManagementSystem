from tests.conftest import login


def test_login_logout_and_protected_page(client):
    assert client.get("/").status_code == 302
    assert login(client).status_code == 302
    assert client.get("/").status_code == 200
    assert client.post("/logout").status_code == 302
    assert client.get("/api/dashboard").status_code == 401


def test_invalid_login(client):
    response = client.post("/login", data={"username": "admin", "password": "wrong"})
    assert response.status_code == 200
    assert b"Invalid username or password" in response.data


def test_health_check_is_public_and_ready(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_role_permissions(staff_client):
    assert staff_client.get("/staff").status_code == 403
    assert staff_client.get("/reports").status_code == 403
    assert staff_client.post("/api/factory/start", json={}).status_code == 403
    assert staff_client.get("/visitors").status_code == 200


def test_landing_page_is_public(client):
    response = client.get("/landing")
    assert response.status_code == 200
    assert b"ParkSmart" in response.data
    assert b"Live Territory Status" in response.data

