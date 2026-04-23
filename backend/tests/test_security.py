from app.core.security import hash_password, verify_password

def test_hash_and_verify():
    pw = "supersecret"
    h = hash_password(pw)
    assert h != pw
    assert verify_password(pw, h)

def test_wrong_password_fails():
    h = hash_password("correct")
    assert not verify_password("wrong", h)

def test_different_hashes():
    h1 = hash_password("same")
    h2 = hash_password("same")
    assert h1 != h2  # bcrypt salts differ
