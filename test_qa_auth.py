"""QA test: Auth flow (register, login, JWT, protected endpoints)"""
import json, subprocess, sys

BASE = "http://localhost:8000"

def curl(method, path, headers=None, data=None, timeout=15):
    cmd = ["curl", "-s", "-X", method, f"{BASE}{path}"]
    if headers:
        for k, v in headers.items():
            cmd += ["-H", f"{k}: {v}"]
    if data:
        cmd += ["-H", "Content-Type: application/json", "-d", json.dumps(data)]
    if method == "GET" and not headers:
        cmd += ["-w", "\n%{http_code}"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return r.stdout, r.stderr

def json_of(text):
    try:
        return json.loads(text.strip().split("\n")[0])
    except:
        return None

passed = 0
failed = 0

def check(name, ok, detail=""):
    global passed, failed
    if ok:
        print(f"  PASS  {name}")
        passed += 1
    else:
        print(f"  FAIL  {name}  {detail}")
        failed += 1

print("=" * 60)
print("QA: Auth Flow Tests")
print("=" * 60)

# 1. Register
out, _ = curl("POST", "/api/v1/auth/register", data={
    "username": "qauser", "email": "qa@test.com", "password": "QaTest123!"
})
d = json_of(out)
check("Register creates user", d and d.get("id") == 2, f"got: {out.strip()}")

# 2. Duplicate register
out, _ = curl("POST", "/api/v1/auth/register", data={
    "username": "qauser", "email": "qa@test.com", "password": "QaTest123!"
})
check("Duplicate returns 409", "already taken" in out, f"got: {out.strip()}")

# 3. Login
out, _ = curl("POST", "/api/v1/auth/login", data={
    "username": "qauser", "password": "QaTest123!"
})
d = json_of(out)
token = d.get("access_token", "") if d else ""
check("Login returns access_token", bool(token), f"got: {out.strip()[:100]}")

# 4. Protected with token
out, _ = curl("GET", "/api/v1/protected", headers={"Authorization": f"Bearer {token}"})
d = json_of(out)
check("Protected endpoint with valid token", d and d.get("user") == "qauser", f"got: {out.strip()}")

# 5. Protected without token
out, _ = curl("GET", "/api/v1/protected")
check("Protected without token returns error", "Not authenticated" in out, f"got: {out.strip()[:100]}")

# 6. Protected with bad token
out, _ = curl("GET", "/api/v1/protected", headers={"Authorization": "Bearer BADTOKEN"})
check("Protected with bad token returns error", "Invalid or expired" in out, f"got: {out.strip()[:100]}")

# 7. Wrong password
out, _ = curl("POST", "/api/v1/auth/login", data={
    "username": "qauser", "password": "wrongpass"
})
check("Wrong password rejected", "Invalid username or password" in out, f"got: {out.strip()[:100]}")

# 8. Nonexistent user
out, _ = curl("POST", "/api/v1/auth/login", data={
    "username": "ghost", "password": "test1234"
})
check("Non-existent user rejected", "Invalid username or password" in out, f"got: {out.strip()[:100]}")

print()
print(f"Results: {passed} passed, {failed} failed out of {passed+failed}")
sys.exit(failed)
