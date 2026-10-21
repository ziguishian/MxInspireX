"""Lossless, project-scoped image storage for opaque SDK history.

The SDK still sees its original items. Only the SQLite representation replaces
inline image strings with content-addressed references; no image is discarded.
"""
import hashlib
import zlib


BLOB_KEY = '_aics_session_blob'
LITERAL_KEY = '_aics_session_literal'


class SessionBlobs:
    def __init__(self, db, project_id):
        self.db, self.project_id = db, project_id
        self.encoded, self.decoded = set(), {}

    def pack(self, value):
        if isinstance(value, str) and value.startswith('data:image/'):
            raw = value.encode('utf-8')
            key = hashlib.sha256(raw).hexdigest()
            if key not in self.encoded:
                if not self.db.execute('SELECT 1 FROM sdk_session_blobs WHERE project_id=? AND id=?', (self.project_id, key)).fetchone():
                    self.db.execute('INSERT INTO sdk_session_blobs(project_id,id,body) VALUES(?,?,?)',
                                    (self.project_id, key, zlib.compress(raw)))
                self.encoded.add(key)
            return {BLOB_KEY: key}
        if isinstance(value, list):
            return [self.pack(item) for item in value]
        if isinstance(value, dict):
            packed = {key: self.pack(item) for key, item in value.items()}
            # A tool's literal JSON can use our private keys. Escape it rather
            # than interpreting user-supplied data as a storage reference.
            return {LITERAL_KEY: packed} if BLOB_KEY in value or LITERAL_KEY in value else packed
        return value

    def unpack(self, value):
        if isinstance(value, list):
            return [self.unpack(item) for item in value]
        if isinstance(value, dict):
            if set(value) == {LITERAL_KEY}:
                return {key: self.unpack(item) for key, item in value[LITERAL_KEY].items()}
            if set(value) == {BLOB_KEY}:
                key = value[BLOB_KEY]
                if key not in self.decoded:
                    row = self.db.execute('SELECT body FROM sdk_session_blobs WHERE project_id=? AND id=?',
                                          (self.project_id, key)).fetchone()
                    if row is None:
                        raise ValueError('会话图片记录缺失，已停止恢复以保留原始记录')
                    raw = zlib.decompress(row[0])
                    if hashlib.sha256(raw).hexdigest() != key:
                        raise ValueError('会话图片记录校验失败，已停止恢复')
                    self.decoded[key] = raw.decode('utf-8')
                return self.decoded[key]
            return {key: self.unpack(item) for key, item in value.items()}
        return value
