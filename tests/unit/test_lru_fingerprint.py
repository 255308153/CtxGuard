import pytest
from ctxguard.storage.db import DatabaseManager
from ctxguard.storage.repository_fingerprint import FingerprintRepository

def test_lru_eviction(tmp_path):
    db_path = tmp_path / "test_lru.db"
    db_mgr = DatabaseManager(str(db_path))
    repo = FingerprintRepository(db_mgr)

    # Save 3 fingerprints with max_records=2
    repo.save_fingerprint("hash_1", "sess_1", "content 1", max_records=2)
    repo.save_fingerprint("hash_2", "sess_1", "content 2", max_records=2)

    # Access hash_1 so it becomes more recently used than hash_2
    assert repo.get_content("hash_1") == "content 1"

    # Insert hash_3 -> should evict hash_2 (least recently used)
    repo.save_fingerprint("hash_3", "sess_1", "content 3", max_records=2)

    assert repo.get_content("hash_1") == "content 1"
    assert repo.get_content("hash_3") == "content 3"
    assert repo.get_content("hash_2") is None  # Evicted!
