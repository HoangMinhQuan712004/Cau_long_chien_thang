from tests.conftest import API


async def test_register_login_me_logout(anon):
    payload = {"email": "Auth@Test.vn", "password": "password123", "full_name": "Test"}
    r = await anon.post(f"{API}/auth/register", json=payload)
    assert r.status_code == 201
    assert r.json()["role"] == "customer"
    assert r.json()["email"] == "auth@test.vn"

    r = await anon.post(f"{API}/auth/register", json=payload)
    assert r.status_code == 409

    r = await anon.get(f"{API}/auth/me")
    assert r.status_code == 200

    r = await anon.post(f"{API}/auth/refresh")
    assert r.status_code == 200

    await anon.post(f"{API}/auth/logout")
    anon.cookies.clear()
    assert (await anon.get(f"{API}/auth/me")).status_code == 401

    r = await anon.post(
        f"{API}/auth/login", json={"email": "auth@test.vn", "password": "wrong-pass"}
    )
    assert r.status_code == 401
    r = await anon.post(
        f"{API}/auth/login", json={"email": "auth@test.vn", "password": "password123"}
    )
    assert r.status_code == 200
