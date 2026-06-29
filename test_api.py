"""Integration tests for the crypto analysis API."""
import asyncio
import httpx
import os
import sys

BASE = "http://127.0.0.1:8000"

passed = 0
failed = 0


async def test(name, method, path, expected_status, expected_has=None, json_body=None, headers=None):
    global passed, failed
    async with httpx.AsyncClient() as client:
        try:
            if method == "GET":
                resp = await client.get(f"{BASE}{path}", headers=headers or {})
            elif method == "POST":
                resp = await client.post(f"{BASE}{path}", json=json_body or {}, headers=headers or {})
            status_ok = resp.status_code == expected_status
            body = resp.text
            detail = ""
            if status_ok and expected_has:
                if expected_has not in body:
                    status_ok = False
            if status_ok:
                print(f"  PASS [{resp.status_code}] {method} {path}")
                passed += 1
            else:
                print(f"  FAIL [{resp.status_code}] {method} {path} (expected {expected_status})")
                print(f"       body: {body[:200]}")
                failed += 1
        except Exception as e:
            print(f"  FAIL {method} {path} — {e}")
            failed += 1


async def main():
    global passed, failed

    # Test 1: Register
    await test("Register user", "POST", "/api/v1/auth/register", 201,
               json_body={"username": "testuser", "email": "test@example.com", "password": "secret123"})

    # Test 2: Duplicate register -> 409
    await test("Register duplicate", "POST", "/api/v1/auth/register", 409,
               json_body={"username": "testuser", "email": "test@example.com", "password": "secret123"})

    # Test 3: Login -> get token
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{BASE}/api/v1/auth/login",
                                 json={"username": "testuser", "password": "secret123"})
        if resp.status_code == 200:
            print(f"  PASS [200] POST /api/v1/auth/login  (token received)")
            passed += 1
            data = resp.json()
            token = data.get("access_token", "")
            if not token:
                print(f"  FAIL no access_token in response")
                failed += 1
            print(f"  => token prefix: {token[:20]}...")
        else:
            print(f"  FAIL [{resp.status_code}] POST /api/v1/auth/login (expected 200)")
            print(f"       body: {resp.text[:200]}")
            failed += 1
            token = ""

    # Test 4: Protected with valid token
    if token:
        await test("Protected with token", "GET", "/api/v1/protected", 200,
                   headers={"Authorization": f"Bearer {token}"})

    # Test 5: Protected without token -> 401
    await test("Protected no token", "GET", "/api/v1/protected", 401)

    # Test 6: Protected with bad token -> 401
    await test("Protected bad token", "GET", "/api/v1/protected", 401,
               headers={"Authorization": "Bearer invalidtoken123"})

    # Test 7: Login wrong password -> 401
    await test("Login wrong password", "POST", "/api/v1/auth/login", 401,
               json_body={"username": "testuser", "password": "wrongpass"})

    # Test 8: Health endpoint
    await test("Health check", "GET", "/health", 200)

    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed out of {passed+failed} tests")

    # Clean up test DB
    for f in ["crypto_analysis.db"]:
        if os.path.exists(f):
            os.remove(f)
            print(f"Cleaned up {f}")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
